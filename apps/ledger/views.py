import datetime

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts import roles
from apps.accounts.permissions import require_capability
from apps.audit.services import Action, record
from apps.core.exports import table_response
from apps.core.models import Company, FiscalYear

from .forms import (
    AccountForm,
    JournalHeaderForm,
    JournalRowFormSet,
    LockForm,
    PeriodFilterForm,
    ReverseForm,
    SubAccountForm,
)
from .models import Account, Journal, JournalLine, JournalSource, Section, Side, SubAccount, TaxCategory
from .selectors import fiscal_year_start, general_ledger, trial_balance
from .services import LineInput, post_journal, reverse_journal


def _period(request) -> tuple[PeriodFilterForm, datetime.date, datetime.date]:
    today = datetime.date.today()
    defaults = {"date_from": fiscal_year_start(today), "date_to": today}
    form = PeriodFilterForm(request.GET if "date_from" in request.GET else None, initial=defaults)
    if form.is_bound and form.is_valid():
        return form, form.cleaned_data["date_from"], form.cleaned_data["date_to"]
    return form, defaults["date_from"], defaults["date_to"]


def _entry_options() -> dict:
    return {
        "accounts": [
            {
                "id": a.pk,
                "label": f"{a.code} {a.name}",
                "section": a.get_section_display(),
                "tax": a.default_tax_category_id,
            }
            for a in Account.objects.filter(is_active=True)
        ],
        "subAccounts": [
            {"id": s.pk, "account": s.account_id, "label": s.name}
            for s in SubAccount.objects.filter(is_active=True)
        ],
        "taxes": [{"id": t.pk, "label": t.name} for t in TaxCategory.objects.filter(is_active=True)],
    }


def _rows_from_journal(journal: Journal) -> list[dict]:
    debits = [ln for ln in journal.lines.all() if ln.tax_base_id is None and ln.side == Side.DEBIT]
    credits = [ln for ln in journal.lines.all() if ln.tax_base_id is None and ln.side == Side.CREDIT]
    rows = []
    for i in range(max(len(debits), len(credits))):
        row = {"description": ""}
        for side, items in (("debit", debits), ("credit", credits)):
            if i < len(items):
                ln = items[i]
                row.update(
                    {
                        f"{side}_account": str(ln.account_id),
                        f"{side}_sub_account": str(ln.sub_account_id or ""),
                        f"{side}_tax_category": str(ln.tax_category_id or ""),
                        f"{side}_amount": str(ln.gross_amount),
                    }
                )
                row["description"] = row["description"] or (
                    ln.description if ln.description != journal.description else ""
                )
        rows.append(row)
    return rows


def _rows_from_post(data) -> list[dict]:
    total = int(data.get("rows-TOTAL_FORMS") or 0)
    fields = [
        "debit_account",
        "debit_sub_account",
        "debit_tax_category",
        "debit_amount",
        "credit_account",
        "credit_sub_account",
        "credit_tax_category",
        "credit_amount",
        "description",
    ]
    return [{f: data.get(f"rows-{i}-{f}", "") for f in fields} for i in range(min(total, 200))]


@require_capability(roles.LEDGER_EDIT)
def journal_create(request):
    header = JournalHeaderForm(request.POST or None, initial={"date": datetime.date.today()})
    formset = JournalRowFormSet(request.POST or None, prefix="rows")
    errors: list[str] = []
    if request.method == "POST":
        rows = _rows_from_post(request.POST)
        if header.is_valid() and formset.is_valid():
            lines = []
            for row in formset.cleaned_data:
                for side_key, side in (("debit", Side.DEBIT), ("credit", Side.CREDIT)):
                    if row.get(f"{side_key}_account"):
                        lines.append(
                            LineInput(
                                account=row[f"{side_key}_account"],
                                side=side,
                                amount=row[f"{side_key}_amount"],
                                tax_category=row[f"{side_key}_tax_category"],
                                sub_account=row[f"{side_key}_sub_account"],
                                description=row["description"],
                            )
                        )
            try:
                source = JournalSource.OPENING if header.cleaned_data["is_opening"] else JournalSource.MANUAL
                journal = post_journal(
                    header.cleaned_data["date"],
                    header.cleaned_data["description"],
                    lines,
                    source=source,
                    user=request.user,
                )
            except ValidationError as e:
                errors.extend(e.messages)
            else:
                messages.success(request, f"仕訳 {journal.number} を登録しました。")
                if "continue" in request.POST:
                    return redirect("ledger:journal_new")
                return redirect("ledger:journal_detail", journal.pk)
        for i, form in enumerate(formset.forms, 1):
            errors.extend(f"{i}行目: {e}" for e in form.non_field_errors())
            errors.extend(
                f"{i}行目: {f} {', '.join(errs)}" for f, errs in form.errors.items() if f != "__all__"
            )
        errors.extend(formset.non_form_errors())
    else:
        rows = [{}, {}]
        if copy_id := request.GET.get("copy"):
            source = get_object_or_404(Journal.objects.prefetch_related("lines"), pk=copy_id)
            rows = _rows_from_journal(source)
            header = JournalHeaderForm(
                initial={"date": datetime.date.today(), "description": source.description}
            )
    return render(
        request,
        "ledger/journal_form.html",
        {
            "header": header,
            "errors": errors,
            "rows_json": rows,
            "options": _entry_options(),
            "sides": [("debit", "bg-sky-50/40"), ("credit", "bg-rose-50/40")],
        },
    )


@require_capability(roles.VIEW)
def journal_list(request):
    period_form, date_from, date_to = _period(request)
    journals = Journal.objects.filter(date__gte=date_from, date__lte=date_to).select_related("created_by")
    account_id = request.GET.get("account")
    if account_id:
        journals = journals.filter(lines__account_id=account_id).distinct()
    if q := request.GET.get("q", "").strip():
        journals = journals.filter(
            Q(number__icontains=q) | Q(description__icontains=q) | Q(lines__description__icontains=q)
        ).distinct()
    if source := request.GET.get("source"):
        journals = journals.filter(source=source)
    journals = journals.order_by("date", "id").prefetch_related(
        Prefetch(
            "lines", queryset=JournalLine.objects.select_related("account", "sub_account", "tax_category")
        ),
        "reversed_by",
    )
    if request.GET.get("format") in ("csv", "xlsx"):
        rows = (
            [
                j.date,
                j.number,
                ln.line_no,
                ln.get_side_display(),
                ln.account.code,
                ln.account.name,
                ln.sub_account.name if ln.sub_account else "",
                ln.tax_category or "",
                ln.amount,
                ln.tax_amount,
                ln.description,
                j.get_source_display(),
            ]
            for j in journals
            for ln in j.lines.all()
        )
        return table_response(
            request.GET["format"],
            f"仕訳帳_{date_from}_{date_to}",
            [
                "日付",
                "仕訳番号",
                "行",
                "貸借",
                "科目コード",
                "勘定科目",
                "補助科目",
                "税区分",
                "金額",
                "消費税額",
                "摘要",
                "発生元",
            ],
            rows,
        )
    page = Paginator(journals, 30).get_page(request.GET.get("page"))
    return render(
        request,
        "ledger/journal_list.html",
        {
            "page": page,
            "period_form": period_form,
            "accounts": Account.objects.all(),
            "sources": JournalSource.choices,
        },
    )


@require_capability(roles.VIEW)
def journal_detail(request, pk):
    journal = get_object_or_404(
        Journal.objects.select_related("created_by", "reverses", "source_type").prefetch_related(
            Prefetch(
                "lines", queryset=JournalLine.objects.select_related("account", "sub_account", "tax_category")
            )
        ),
        pk=pk,
    )
    reverse_form = ReverseForm(request.POST or None)
    if request.method == "POST":
        if not request.user.can(roles.LEDGER_EDIT):
            messages.error(request, "権限がありません。")
        elif reverse_form.is_valid():
            try:
                reversal = reverse_journal(
                    journal,
                    reverse_form.cleaned_data["date"],
                    reverse_form.cleaned_data["reason"],
                    user=request.user,
                )
            except ValidationError as e:
                reverse_form.add_error(None, e)
            else:
                messages.success(request, f"取消仕訳 {reversal.number} を登録しました。")
                return redirect("ledger:journal_detail", reversal.pk)
    return render(request, "ledger/journal_detail.html", {"journal": journal, "reverse_form": reverse_form})


@require_capability(roles.VIEW)
def trial_balance_view(request):
    period_form, date_from, date_to = _period(request)
    tb = trial_balance(date_from, date_to)
    if request.GET.get("format") in ("csv", "xlsx"):
        rows = (
            [
                r.account.code,
                r.account.name,
                r.account.get_section_display(),
                r.opening,
                r.debit,
                r.credit,
                r.closing,
            ]
            for r in tb.rows
        )
        return table_response(
            request.GET["format"],
            f"試算表_{date_from}_{date_to}",
            ["科目コード", "勘定科目", "区分", "期首・繰越残高", "借方", "貸方", "期末残高"],
            rows,
        )
    return render(request, "ledger/trial_balance.html", {"tb": tb, "period_form": period_form})


@require_capability(roles.VIEW)
def general_ledger_view(request):
    period_form, date_from, date_to = _period(request)
    accounts = Account.objects.all()
    account = accounts.filter(pk=request.GET.get("account") or 0).first() or Account.by_key("bank")
    sub_account = account.sub_accounts.filter(pk=request.GET.get("sub_account") or 0).first()
    opening, entries = general_ledger(account, date_from, date_to, sub_account)
    if request.GET.get("format") in ("csv", "xlsx"):
        rows = [["", "", "前期・前月繰越", "", "", "", opening]] + [
            [
                e.line.journal.date,
                e.line.journal.number,
                e.line.description,
                e.counterpart,
                e.debit,
                e.credit,
                e.balance,
            ]
            for e in entries
        ]
        return table_response(
            request.GET["format"],
            f"総勘定元帳_{account.name}_{date_from}_{date_to}",
            ["日付", "仕訳番号", "摘要", "相手科目", "借方", "貸方", "残高"],
            rows,
        )
    return render(
        request,
        "ledger/general_ledger.html",
        {
            "period_form": period_form,
            "accounts": accounts,
            "account": account,
            "sub_account": sub_account,
            "opening": opening,
            "entries": entries,
            "total_debit": sum(e.debit for e in entries),
            "total_credit": sum(e.credit for e in entries),
            "closing": entries[-1].balance if entries else opening,
        },
    )


@require_capability(roles.VIEW)
def account_list(request):
    groups: dict[str, list[Account]] = {}
    for account in Account.objects.select_related("default_tax_category").prefetch_related("sub_accounts"):
        groups.setdefault(account.get_section_display(), []).append(account)
    ordered = [(s.label, groups[s.label]) for s in Section if s.label in groups]
    return render(request, "ledger/account_list.html", {"groups": ordered})


@require_capability(roles.LEDGER_EDIT)
def account_edit(request, pk=None):
    account = get_object_or_404(Account, pk=pk) if pk else None
    form = AccountForm(request.POST or None, instance=account, prefix="account")
    sub_form = SubAccountForm(request.POST or None, prefix="sub")
    if request.method == "POST":
        if "add_sub" in request.POST and account:
            if sub_form.is_valid():
                sub = sub_form.save(commit=False)
                sub.account = account
                sub.save()
                messages.success(request, f"補助科目「{sub.name}」を追加しました。")
                return redirect("ledger:account_edit", account.pk)
        elif form.is_valid():
            if account and account.system_key and not form.cleaned_data["is_active"]:
                form.add_error("is_active", "システムで使用する科目は無効にできません。")
            elif account and account.system_key and form.cleaned_data["section"] != account.section:
                form.add_error("section", "システムで使用する科目の区分は変更できません。")
            else:
                account = form.save()
                messages.success(request, f"勘定科目「{account.name}」を保存しました。")
                return redirect("ledger:accounts")
    return render(
        request,
        "ledger/account_form.html",
        {
            "form": form,
            "sub_form": sub_form,
            "object": account,
            "sub_accounts": account.sub_accounts.all() if account else [],
        },
    )


@require_POST
@require_capability(roles.LEDGER_EDIT)
def sub_account_toggle(request, pk):
    sub = get_object_or_404(SubAccount, pk=pk)
    sub.is_active = not sub.is_active
    sub.save()
    return redirect("ledger:account_edit", sub.account_id)


@require_capability(roles.VIEW)
def tax_category_list(request):
    return render(request, "ledger/tax_category_list.html", {"taxes": TaxCategory.objects.all()})


@require_capability(roles.PERIOD_CLOSE)
def period_close(request):
    company = Company.load()
    lock_form = LockForm(request.POST if "lock" in request.POST else None, instance=company)
    if request.method == "POST":
        if "lock" in request.POST and lock_form.is_valid():
            lock_form.save()
            messages.success(request, "月次締め日を更新しました。")
            return redirect("ledger:period_close")
        if fy_id := request.POST.get("fiscal_year"):
            fy = get_object_or_404(FiscalYear, pk=fy_id)
            closing = request.POST.get("action") == "close"
            if closing and FiscalYear.objects.filter(start_date__lt=fy.start_date, is_closed=False).exists():
                messages.error(request, "前の会計期間を先に締めてください。")
            elif (
                not closing
                and FiscalYear.objects.filter(start_date__gt=fy.start_date, is_closed=True).exists()
            ):
                messages.error(request, "後の会計期間の締めを先に解除してください。")
            else:
                fy.is_closed = closing
                fy.save()
                record(
                    Action.CONFIRM if closing else Action.OTHER,
                    fy,
                    note="決算締め" if closing else "決算締め解除",
                    user=request.user,
                )
                messages.success(request, f"{fy.name}を{'締めました' if closing else '締め解除しました'}。")
            return redirect("ledger:period_close")
    return render(
        request,
        "ledger/period_close.html",
        {
            "lock_form": lock_form,
            "fiscal_years": FiscalYear.objects.order_by("start_date"),
        },
    )
