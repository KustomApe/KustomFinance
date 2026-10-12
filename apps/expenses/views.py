from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts import roles
from apps.accounts.permissions import require_capability
from apps.ledger.models import Account

from . import services
from .forms import ApproveForm, ClaimForm, LineFormSet, PayForm
from .models import ExpenseClaim, ExpenseLine

Status = ExpenseClaim.Status


def _can_view(user, claim) -> bool:
    return claim.applicant_id == user.pk or user.can(roles.LEDGER_EDIT)


@require_capability(roles.VIEW)
def claim_list(request):
    tab = request.GET.get("tab", "mine")
    claims = ExpenseClaim.objects.select_related("applicant")
    if tab == "approval" and request.user.can(roles.LEDGER_EDIT):
        claims = claims.filter(status=Status.SUBMITTED)
    elif tab == "unpaid" and request.user.can(roles.LEDGER_EDIT):
        claims = claims.filter(status=Status.APPROVED)
    elif tab == "all" and request.user.can(roles.LEDGER_EDIT):
        pass
    else:
        tab = "mine"
        claims = claims.filter(applicant=request.user)
    page = Paginator(claims, 30).get_page(request.GET.get("page"))
    return render(
        request,
        "expenses/list.html",
        {
            "page": page,
            "tab": tab,
            "approval_count": ExpenseClaim.objects.filter(status=Status.SUBMITTED).count(),
        },
    )


@require_capability(roles.EXPENSE_SUBMIT)
def claim_edit(request, pk=None):
    claim = get_object_or_404(ExpenseClaim, pk=pk) if pk else ExpenseClaim(applicant=request.user)
    if claim.pk and (claim.applicant_id != request.user.pk or not claim.is_editable):
        messages.error(request, "この申請は編集できません。")
        return redirect("expenses:detail", claim.pk)
    form = ClaimForm(request.POST or None, instance=claim)
    formset = LineFormSet(request.POST or None, request.FILES or None, instance=claim, prefix="lines")
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        claim = form.save()
        formset.instance = claim
        formset.save()
        claim.recalculate()
        claim.save()
        if "submit" in request.POST:
            try:
                claim = services.submit(claim, request.user)
            except ValidationError as e:
                for m in e.messages:
                    messages.error(request, m)
                return redirect("expenses:edit", claim.pk)
            messages.success(request, f"経費精算 {claim.number} を申請しました。")
            return redirect("expenses:detail", claim.pk)
        messages.success(request, "下書きを保存しました。")
        return redirect("expenses:edit", claim.pk)
    defaults = {str(a.pk): a.default_tax_category_id for a in Account.objects.filter(is_active=True)}
    return render(
        request,
        "expenses/form.html",
        {
            "form": form,
            "formset": formset,
            "claim": claim,
            "account_taxes": defaults,
            "ocr_external": settings.OCR_ENGINE == "claude",
        },
    )


@require_capability(roles.VIEW)
def claim_detail(request, pk):
    claim = get_object_or_404(ExpenseClaim.objects.select_related("applicant", "approver"), pk=pk)
    if not _can_view(request.user, claim):
        raise PermissionDenied
    approve_form = ApproveForm(request.POST if request.POST.get("action") == "approve" else None)
    pay_form = PayForm(
        request.POST if request.POST.get("action") == "pay" else None,
        initial={"account": Account.by_key("bank")},
    )
    if request.method == "POST":
        action = request.POST.get("action")
        is_owner = claim.applicant_id == request.user.pk
        try:
            if action == "submit" and is_owner:
                services.submit(claim, request.user)
                messages.success(request, "申請しました。")
            elif action == "delete" and is_owner and claim.status == Status.DRAFT and not claim.number:
                claim.delete()
                messages.success(request, "下書きを削除しました。")
                return redirect("expenses:list")
            elif not request.user.can(roles.LEDGER_EDIT):
                raise PermissionDenied
            elif action == "approve" and approve_form.is_valid():
                services.approve(claim, request.user, approve_form.cleaned_data["posting_date"])
                messages.success(request, "承認し、経費を計上しました。")
            elif action == "reject":
                services.reject(claim, request.user, request.POST.get("reason", ""))
                messages.success(request, "差し戻しました。")
            elif action == "pay" and pay_form.is_valid():
                services.pay(
                    claim,
                    request.user,
                    pay_form.cleaned_data["date"],
                    pay_form.cleaned_data["account"],
                    pay_form.cleaned_data["sub_account"],
                )
                messages.success(request, "精算しました。")
            elif action == "cancel":
                services.cancel(claim, request.user, request.POST.get("reason", ""))
                messages.success(request, "取り消しました。")
            else:
                messages.error(request, "入力内容を確認してください。")
        except ValidationError as e:
            for m in e.messages:
                messages.error(request, m)
        return redirect("expenses:detail", pk)
    lines = list(claim.lines.select_related("account", "tax_category"))
    for line in lines:
        line.effective_tax = services.effective_tax_category(line)
    return render(
        request,
        "expenses/detail.html",
        {
            "claim": claim,
            "lines": lines,
            "approve_form": approve_form,
            "pay_form": pay_form,
            "is_owner": claim.applicant_id == request.user.pk,
        },
    )


@require_capability(roles.VIEW)
def receipt_file(request, pk):
    line = get_object_or_404(ExpenseLine.objects.select_related("claim"), pk=pk)
    if not _can_view(request.user, line.claim):
        raise PermissionDenied
    if not line.receipt:
        raise Http404
    return FileResponse(line.receipt.open("rb"), filename=line.receipt.name.rsplit("/", 1)[-1])
