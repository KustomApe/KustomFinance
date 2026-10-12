"""前受金・前渡金の充当（販売・購買共通）。

入金・支払のうち請求書に消し込まなかった額（前受金・前渡金）を、後から発行・計上された
請求書・仕入請求書に充当する。充当は入金・支払への消込（allocation）として記録し、
充当時に次の仕訳を計上する。

- 販売: 前受金 / 売掛金
- 購買: 買掛金 / 前渡金

取消は取消仕訳を計上し、消込を「取消」とする（削除しない）。
"""

import datetime
from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import Action, record
from apps.ledger.models import Account, JournalSource, Side
from apps.ledger.services import LineInput, post_journal, reverse_journal

from .documents import DocStatus


@dataclass(frozen=True)
class AdvanceKind:
    source_field: str  # "receipt" / "payment"
    document_field: str  # "invoice" / "bill"
    advance_key: str  # 前受金 / 前渡金 の system_key
    control_key: str  # 売掛金 / 買掛金 の system_key
    advance_label: str
    journal_source: str

    def lines(self, amount: Decimal, partner) -> list[LineInput]:
        advance, control = Account.by_key(self.advance_key), Account.by_key(self.control_key)
        if self.advance_key == "advances_received":  # 前受金 / 売掛金
            debit, credit = advance, control
        else:  # 買掛金 / 前渡金
            debit, credit = control, advance
        return [
            LineInput(debit, Side.DEBIT, amount, partner=partner, description=f"{self.advance_label}充当"),
            LineInput(credit, Side.CREDIT, amount, partner=partner, description=f"{self.advance_label}充当"),
        ]


SALES = AdvanceKind(
    "receipt", "invoice", "advances_received", "accounts_receivable", "前受金", JournalSource.SALES
)
PURCHASE = AdvanceKind(
    "payment", "bill", "advances_paid", "accounts_payable", "前渡金", JournalSource.PURCHASE
)


def available_sources(kind: AdvanceKind, source_model, partner) -> list:
    """取引先の、充当できる残額がある入金・支払。"""
    sources = source_model.objects.filter(partner=partner, status="active").order_by("date", "id")
    return [s for s in sources.prefetch_related("allocations") if s.advance_amount > 0]


@transaction.atomic
def apply_advance(kind: AdvanceKind, source, document, amount: Decimal, date: datetime.date, user=None):
    source = type(source).objects.select_for_update().get(pk=source.pk)
    document = type(document).objects.select_for_update().get(pk=document.pk)
    if source.status != "active":
        raise ValidationError("取り消された入出金からは充当できません。")
    if source.partner_id != document.partner_id:
        raise ValidationError("取引先が異なります。")
    if document.status != DocStatus.ISSUED:
        raise ValidationError("発行・計上済みの帳票にのみ充当できます。")
    if amount <= 0:
        raise ValidationError("充当額を入力してください。")
    if amount > source.advance_amount:
        raise ValidationError(f"{kind.advance_label}の残額（{source.advance_amount:,}円）を超えています。")
    if amount > document.outstanding:
        raise ValidationError(f"未決済額（{document.outstanding:,}円）を超えています。")
    if date < source.date:
        raise ValidationError("充当日は入出金日以降にしてください。")
    journal = post_journal(
        date,
        f"{document.partner.name} {kind.advance_label}充当 {source.number} → {document.number}",
        kind.lines(amount, document.partner),
        source=kind.journal_source,
        source_object=document,
        user=user,
    )
    allocation = source.allocations.create(
        **{kind.document_field: document}, amount=amount, applied_date=date, applied_journal=journal
    )
    record(Action.OTHER, document, note=f"{kind.advance_label}充当 {source.number} {amount:,}円", user=user)
    return allocation


@transaction.atomic
def cancel_application(kind: AdvanceKind, allocation, reason: str, user=None):
    allocation = type(allocation).objects.select_for_update().get(pk=allocation.pk)
    if not allocation.is_advance_application:
        raise ValidationError("入出金時の消込は、入出金そのものを取り消してください。")
    if allocation.cancelled_at:
        raise ValidationError("この充当はすでに取り消されています。")
    if not reason.strip():
        raise ValidationError("取消理由を入力してください。")
    journal = allocation.applied_journal
    reverse_journal(journal, max(datetime.date.today(), journal.date), reason, user=user)
    allocation.cancelled_at = timezone.now()
    allocation.save(update_fields=["cancelled_at"])
    document = getattr(allocation, kind.document_field)
    record(Action.CANCEL, document, note=f"{kind.advance_label}充当の取消: {reason}", user=user)
    return allocation


def has_active_applications(source) -> bool:
    return source.allocations.filter(applied_journal__isnull=False, cancelled_at__isnull=True).exists()
