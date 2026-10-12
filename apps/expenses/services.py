import datetime

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import Action, record
from apps.core.numbering import next_number
from apps.ledger.models import Account, JournalSource, Side, TaxCategory
from apps.ledger.services import LineInput, post_journal, reverse_journal
from apps.purchasing.services import purchase_tax_code

from .models import ExpenseClaim, ExpenseLine

Status = ExpenseClaim.Status
RATE_KEYS = {"P10": "10", "P8R": "8R"}


def effective_tax_category(line: ExpenseLine) -> TaxCategory:
    """登録番号のない領収書（特例に該当しないもの）は経過措置の税区分に読み替える。"""
    code = line.tax_category.code
    if code in RATE_KEYS and not line.payee_registration_number and not line.invoice_exempt:
        return TaxCategory.objects.get(code=purchase_tax_code(RATE_KEYS[code], False, line.date))
    return line.tax_category


def _lock(claim: ExpenseClaim) -> ExpenseClaim:
    return ExpenseClaim.objects.select_for_update().get(pk=claim.pk)


@transaction.atomic
def submit(claim: ExpenseClaim, user) -> ExpenseClaim:
    claim = _lock(claim)
    if not claim.is_editable:
        raise ValidationError("この申請は提出できません。")
    if claim.applicant_id != user.pk:
        raise ValidationError("本人のみ申請できます。")
    if not claim.lines.exists():
        raise ValidationError("明細を1行以上入力してください。")
    claim.recalculate()
    if not claim.number:
        claim.number = next_number("expense", timezone.localdate())
    claim.status = Status.SUBMITTED
    claim.submitted_at = timezone.now()
    claim.reject_reason = ""
    claim.save()
    record(Action.OTHER, claim, note="申請", user=user)
    return claim


@transaction.atomic
def approve(claim: ExpenseClaim, user, posting_date: datetime.date) -> ExpenseClaim:
    """承認して経費を計上する: 各経費科目・仮払消費税 / 未払金。"""
    claim = _lock(claim)
    if claim.status != Status.SUBMITTED:
        raise ValidationError("承認待ちの申請のみ承認できます。")
    if claim.applicant_id == user.pk and not user.is_superuser:
        raise ValidationError("自分の申請は承認できません。")
    common = {"department": claim.department, "project": claim.project}
    lines = [
        LineInput(
            line.account,
            Side.DEBIT,
            line.amount,
            effective_tax_category(line),
            description=f"{line.payee} {line.description}",
            **common,
        )
        for line in claim.lines.select_related("account", "tax_category")
    ]
    lines.append(
        LineInput(
            Account.by_key("accrued_payable"),
            Side.CREDIT,
            claim.total,
            description=f"経費精算 {claim.applicant}",
            **common,
        )
    )
    claim.journal = post_journal(
        posting_date,
        f"経費精算 {claim.number} {claim.applicant} {claim.title}",
        lines,
        source=JournalSource.EXPENSE,
        source_object=claim,
        user=user,
    )
    claim.status = Status.APPROVED
    claim.approver = user
    claim.approved_at = timezone.now()
    claim.save()
    record(Action.CONFIRM, claim, note="承認", user=user)
    return claim


@transaction.atomic
def reject(claim: ExpenseClaim, user, reason: str) -> ExpenseClaim:
    claim = _lock(claim)
    if claim.status != Status.SUBMITTED:
        raise ValidationError("承認待ちの申請のみ差し戻せます。")
    if not reason.strip():
        raise ValidationError("差戻し理由を入力してください。")
    claim.status = Status.REJECTED
    claim.reject_reason = reason
    claim.save()
    record(Action.OTHER, claim, note=f"差戻し: {reason}", user=user)
    return claim


@transaction.atomic
def pay(claim: ExpenseClaim, user, date: datetime.date, account: Account, sub_account=None) -> ExpenseClaim:
    """精算（立替金の支払）: 未払金 / 預金・現金。"""
    claim = _lock(claim)
    if claim.status != Status.APPROVED:
        raise ValidationError("承認済みの申請のみ精算できます。")
    claim.payment_journal = post_journal(
        date,
        f"経費精算 支払 {claim.number} {claim.applicant}",
        [
            LineInput(Account.by_key("accrued_payable"), Side.DEBIT, claim.total),
            LineInput(account, Side.CREDIT, claim.total, sub_account=sub_account),
        ],
        source=JournalSource.EXPENSE,
        source_object=claim,
        user=user,
    )
    claim.status = Status.PAID
    claim.paid_date = date
    claim.save()
    record(Action.OTHER, claim, note="精算", user=user)
    return claim


@transaction.atomic
def cancel(claim: ExpenseClaim, user, reason: str) -> ExpenseClaim:
    """承認済み（未精算）の申請を取り消す。計上仕訳は取消仕訳で戻す。"""
    claim = _lock(claim)
    if claim.status != Status.APPROVED:
        raise ValidationError("承認済み・未精算の申請のみ取り消せます。")
    if not reason.strip():
        raise ValidationError("取消理由を入力してください。")
    reverse_journal(claim.journal, max(datetime.date.today(), claim.journal.date), reason, user=user)
    claim.status = Status.CANCELLED
    claim.save()
    record(Action.CANCEL, claim, note=reason, user=user)
    return claim
