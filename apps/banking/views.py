import datetime

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.views.decorators.http import require_POST

from apps.accounts import roles
from apps.accounts.permissions import require_capability
from apps.ledger.models import Account, TaxCategory
from apps.masters.models import Partner
from apps.purchasing.models import Bill
from apps.sales.models import Invoice

from . import services
from .forms import BankAccountForm, ImportForm, ImportProfileForm, PostForm, RuleForm
from .models import BankAccount, BankRule, BankTransaction, ImportBatch, ImportProfile

# ---- 口座・CSV形式・ルールの登録（シンプルな一覧＋編集） ----

SETTINGS_PAGES = {
    "account": (
        BankAccount,
        BankAccountForm,
        "銀行口座",
        ["name", "account", "sub_account", "import_profile", "is_active"],
    ),
    "profile": (
        ImportProfile,
        ImportProfileForm,
        "明細CSV形式",
        [
            "name",
            "skip_rows",
            "date_column",
            "description_column",
            "withdrawal_column",
            "deposit_column",
            "amount_column",
            "balance_column",
        ],
    ),
    "rule": (
        BankRule,
        RuleForm,
        "自動仕訳ルール",
        ["priority", "keyword", "direction", "account", "tax_category", "partner", "is_active"],
    ),
}


def _settings_list(key):
    model, _, title, columns = SETTINGS_PAGES[key]

    @require_capability(roles.VIEW)
    def view(request):
        fields = [model._meta.get_field(c) for c in columns]
        rows = [
            {
                "url": reverse(f"banking:{key}_edit", args=[o.pk]),
                "cells": [
                    (f, getattr(o, f"get_{f.name}_display")() if f.choices else getattr(o, f.name))
                    for f in fields
                ],
            }
            for o in model.objects.all()
        ]
        return render(
            request,
            "masters/list.html",
            {
                "m": {"key": key},
                "title": title,
                "headers": [f.verbose_name for f in fields],
                "rows": rows,
                "new_url": reverse(f"banking:{key}_new"),
                "page": None,
                "edit_cap": roles.LEDGER_EDIT,
            },
        )

    return view


def _settings_edit(key):
    model, form_class, title, _ = SETTINGS_PAGES[key]

    @require_capability(roles.LEDGER_EDIT)
    def view(request, pk=None):
        obj = get_object_or_404(model, pk=pk) if pk else None
        form = form_class(request.POST or None, instance=obj)
        if request.method == "POST" and form.is_valid():
            form.save()
            messages.success(request, f"{title}を保存しました。")
            return redirect(f"banking:{key}_list")
        return render(
            request,
            "masters/form.html",
            {
                "m": {"key": key},
                "title": title,
                "form": form,
                "object": obj,
                "list_url": reverse(f"banking:{key}_list"),
            },
        )

    return view


def settings_urlpatterns():
    patterns = []
    for key in SETTINGS_PAGES:
        patterns += [
            path(f"{key}s/", _settings_list(key), name=f"{key}_list"),
            path(f"{key}s/new/", _settings_edit(key), name=f"{key}_new"),
            path(f"{key}s/<int:pk>/", _settings_edit(key), name=f"{key}_edit"),
        ]
    return patterns


# ---- 明細の取込・処理 ----


@require_capability(roles.LEDGER_EDIT)
def import_view(request):
    form = ImportForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        upload = form.cleaned_data["file"]
        try:
            batch, errors = services.import_statement(
                form.cleaned_data["bank_account"], upload.name, upload.read(), request.user
            )
        except ValidationError as e:
            for m in e.messages:
                messages.error(request, m)
        else:
            messages.success(
                request, f"{batch.imported}件を取り込みました（重複 {batch.skipped}件はスキップ）。"
            )
            for m in errors[:20]:
                messages.warning(request, m)
            return redirect(f"{reverse('banking:transactions')}?account={batch.bank_account_id}")
    return render(
        request,
        "banking/import.html",
        {
            "form": form,
            "batches": ImportBatch.objects.select_related("bank_account", "created_by")[:20],
            "has_accounts": BankAccount.objects.exists(),
        },
    )


def _row_context(tx: BankTransaction, rules, error: str = "") -> dict:
    ctx = {"tx": tx, "error": error}
    if tx.status == BankTransaction.Status.UNPROCESSED:
        ctx["candidates"] = services.candidates(tx)
        ctx["rule"] = services.match_rule(tx, rules)
    return ctx


def _options() -> dict:
    return {
        "accounts": Account.objects.filter(is_active=True),
        "taxes": TaxCategory.objects.filter(is_active=True),
        "partners": Partner.objects.filter(is_active=True),
    }


@require_capability(roles.VIEW)
def transactions(request):
    accounts = BankAccount.objects.filter(is_active=True)
    qs = BankTransaction.objects.select_related("bank_account", "journal")
    account_id = request.GET.get("account")
    if account_id:
        qs = qs.filter(bank_account_id=account_id)
    status = request.GET.get("status", BankTransaction.Status.UNPROCESSED)
    if status:
        qs = qs.filter(status=status)
    if date_from := request.GET.get("date_from"):
        qs = qs.filter(date__gte=date_from)
    if date_to := request.GET.get("date_to"):
        qs = qs.filter(date__lte=date_to)
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    rules = list(BankRule.objects.filter(is_active=True).select_related("account", "tax_category", "partner"))
    rows = [_row_context(tx, rules) for tx in page]
    return render(
        request,
        "banking/transactions.html",
        {
            "page": page,
            "rows": rows,
            "bank_accounts": accounts,
            "status": status,
            "statuses": BankTransaction.Status.choices,
            **_options(),
        },
    )


@require_POST
@require_capability(roles.LEDGER_EDIT)
def transaction_action(request, pk):
    """明細1行の処理（HTMX）。処理後の行を返す。"""
    tx = get_object_or_404(BankTransaction.objects.select_related("bank_account"), pk=pk)
    action = request.POST.get("action")
    error = ""
    try:
        if action == "match":
            model = Invoice if tx.deposit else Bill
            document = get_object_or_404(model, pk=request.POST.get("document"))
            tx = services.apply_match(tx, document, request.user)
        elif action == "rule":
            rule = get_object_or_404(BankRule, pk=request.POST.get("rule"))
            tx = services.post_transaction(
                tx,
                request.user,
                account=rule.account,
                tax_category=rule.tax_category,
                partner=rule.partner,
                description=rule.description,
            )
        elif action == "post":
            form = PostForm(request.POST)
            if not form.is_valid():
                raise ValidationError("相手科目を選択してください。")
            tx = services.post_transaction(tx, request.user, **form.cleaned_data)
        elif action == "ignore":
            tx = services.ignore_transaction(tx, request.POST.get("note", ""))
        elif action == "reopen":
            tx = services.reopen_transaction(tx)
        else:
            raise ValidationError("不明な操作です。")
    except ValidationError as e:
        error = " ".join(e.messages)
        tx.refresh_from_db()
    rules = list(BankRule.objects.filter(is_active=True).select_related("account", "tax_category", "partner"))
    ctx = {"row": _row_context(tx, rules, error), **_options()}
    if not request.htmx:
        if error:
            messages.error(request, error)
        return redirect(request.META.get("HTTP_REFERER") or "banking:transactions")
    return render(request, "banking/_row.html", ctx)


@require_capability(roles.VIEW)
def reconciliation(request):
    as_of = datetime.date.today()
    if raw := request.GET.get("as_of"):
        try:
            as_of = datetime.date.fromisoformat(raw)
        except ValueError:
            pass
    rows = [
        {"bank": b, **services.reconciliation(b, as_of)} for b in BankAccount.objects.filter(is_active=True)
    ]
    return render(request, "banking/reconciliation.html", {"rows": rows, "as_of": as_of})


@require_capability(roles.LEDGER_EDIT)
def manual_form(request, pk):
    tx = get_object_or_404(BankTransaction, pk=pk)
    return render(request, "banking/_manual_form.html", {"tx": tx, **_options()})
