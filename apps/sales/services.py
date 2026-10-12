import datetime
from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.audit.services import Action, record
from apps.core.models import Company
from apps.core.numbering import next_number
from apps.ledger.models import Account, JournalSource, Side, TaxCategory
from apps.ledger.services import LineInput, post_journal, reverse_journal
from apps.masters.doc_services import LINE_FIELDS, copy_document, sales_tax_code
from apps.masters.documents import DocStatus

from .models import Delivery, Invoice, Receipt, ReceiptAllocation


def _allocate_tax(groups: dict, rate_tax: Decimal) -> dict:
    """税率内で科目が複数ある場合、税額を対象額で按分する（端数は最大の科目へ）。"""
    total = sum(groups.values())
    if not total:
        return {k: Decimal(0) for k in groups}
    shares = {
        k: (rate_tax * v / total).quantize(Decimal("1"), rounding="ROUND_FLOOR") for k, v in groups.items()
    }
    largest = max(groups, key=lambda k: abs(groups[k]))
    shares[largest] += rate_tax - sum(shares.values())
    return shares


def post_invoice(invoice: Invoice, user) -> None:
    """請求書発行時の売上仕訳: 売掛金 / 売上高（税率ごとに消費税額を確定値で計上）。"""
    if invoice.total <= 0:
        raise ValidationError("合計金額が0円以下の請求書は発行できません。")
    if not invoice.sales_date:
        invoice.sales_date = invoice.issue_date
    if not invoice.due_date:
        invoice.due_date = invoice.partner.due_date_for(invoice.sales_date)
    default_account = Account.by_key("sales")
    bases: dict[str, dict] = defaultdict(lambda: defaultdict(Decimal))
    for line in invoice.lines.select_related("item__sales_account"):
        account = (line.item.sales_account if line.item else None) or default_account
        bases[line.tax_rate][account] += line.amount
    taxes = {row.rate: row.tax for row in invoice.tax_rows()}
    common = {"partner": invoice.partner, "department": invoice.department, "project": invoice.project}
    lines = [LineInput(Account.by_key("accounts_receivable"), Side.DEBIT, invoice.total, **common)]
    tax_categories = {t.code: t for t in TaxCategory.objects.all()}
    for rate, groups in bases.items():
        shares = _allocate_tax(groups, taxes.get(rate, Decimal(0)))
        for account, base in groups.items():
            gross = base + shares[account]
            if gross == 0:
                continue
            lines.append(
                LineInput(
                    account,
                    Side.CREDIT if gross > 0 else Side.DEBIT,
                    abs(gross),
                    tax_category=tax_categories[sales_tax_code(rate)],
                    tax_amount=abs(shares[account]),
                    **common,
                )
            )
    invoice.journal = post_journal(
        invoice.sales_date,
        f"{invoice.partner.name} 請求書 {invoice.number}",
        lines,
        source=JournalSource.SALES,
        source_object=invoice,
        user=user,
    )


def cancel_invoice(invoice: Invoice, reason: str, user) -> None:
    if invoice.allocations.exclude(receipt__status=Receipt.Status.CANCELLED).exists():
        raise ValidationError("入金消込済みの請求書は取り消せません。先に入金を取り消してください。")
    if invoice.journal:
        reverse_journal(invoice.journal, max(datetime.date.today(), invoice.journal.date), reason, user=user)
    invoice.deliveries.update(invoice=None)


@transaction.atomic
def invoice_from_deliveries(deliveries: list[Delivery], user, issue_date: datetime.date) -> Invoice:
    """複数の納品書をまとめて1枚の請求書（締め請求）を作成する。明細には納品日を取引日として記載する。"""
    if not deliveries:
        raise ValidationError("納品書を選択してください。")
    partners = {d.partner_id for d in deliveries}
    if len(partners) != 1:
        raise ValidationError("同じ取引先の納品書を選択してください。")
    if any(d.invoice_id or d.status != DocStatus.ISSUED for d in deliveries):
        raise ValidationError("発行済みで未請求の納品書のみ選択できます。")
    deliveries = sorted(deliveries, key=lambda d: (d.issue_date, d.pk))
    first = deliveries[0]
    invoice = copy_document(
        first, Invoice, user=user, line_date=first.issue_date, issue_date=issue_date, order=first.order
    )
    invoice.subject = (
        invoice.subject if len(deliveries) == 1 else f"{deliveries[0].issue_date:%Y年%m月}分 ご請求"
    )
    sort = invoice.lines.count()
    for d in deliveries[1:]:
        for line in d.lines.all():
            fields = {f: getattr(line, f) for f in LINE_FIELDS}
            invoice.lines.create(**{**fields, "transaction_date": d.issue_date, "sort_order": sort})
            sort += 1
    invoice.recalculate(Company.load().tax_rounding)
    invoice.save()
    Delivery.objects.filter(pk__in=[d.pk for d in deliveries]).update(invoice=invoice)
    return invoice


@transaction.atomic
def create_receipt(
    *,
    partner,
    date,
    deposit_account,
    deposit_sub_account,
    amount: Decimal,
    fee: Decimal,
    memo: str,
    allocations: list[tuple[Invoice, Decimal]],
    user,
) -> Receipt:
    """入金を登録し、請求書へ消し込む。消し込まなかった額は前受金とする。"""
    allocations = [(inv, amt) for inv, amt in allocations if amt]
    if amount <= 0:
        raise ValidationError("入金額を入力してください。")
    if fee < 0:
        raise ValidationError("手数料は0以上で入力してください。")
    errors = []
    for inv in Invoice.objects.select_for_update().filter(pk__in=[i.pk for i, _ in allocations]):
        amt = dict((i.pk, a) for i, a in allocations)[inv.pk]
        if inv.partner_id != partner.pk or inv.status != DocStatus.ISSUED:
            errors.append(f"請求書 {inv.number} は消込できません。")
        elif amt < 0 or amt > inv.outstanding:
            errors.append(f"請求書 {inv.number} の消込額は 0〜{inv.outstanding:,} 円で入力してください。")
    allocated = sum(a for _, a in allocations)
    if allocated > amount + fee:
        errors.append(f"消込額の合計（{allocated:,}円）が入金額と手数料の合計を超えています。")
    if errors:
        raise ValidationError(errors)

    receipt = Receipt.objects.create(
        number=next_number("receipt", date),
        date=date,
        partner=partner,
        deposit_account=deposit_account,
        deposit_sub_account=deposit_sub_account,
        amount=amount,
        fee=fee,
        memo=memo,
        created_by=user,
    )
    for inv, amt in allocations:
        ReceiptAllocation.objects.create(receipt=receipt, invoice=inv, amount=amt)
    common = {"partner": partner}
    lines = [LineInput(deposit_account, Side.DEBIT, amount, sub_account=deposit_sub_account, **common)]
    if fee:
        lines.append(
            LineInput(
                Account.by_key("fees"),
                Side.DEBIT,
                fee,
                TaxCategory.objects.get(code="P10"),
                description="振込手数料",
                **common,
            )
        )
    if allocated:
        lines.append(LineInput(Account.by_key("accounts_receivable"), Side.CREDIT, allocated, **common))
    if amount + fee - allocated:
        lines.append(
            LineInput(
                Account.by_key("advances_received"),
                Side.CREDIT,
                amount + fee - allocated,
                description="前受金",
                **common,
            )
        )
    receipt.journal = post_journal(
        date,
        f"{partner.name} 入金 {receipt.number}",
        lines,
        source=JournalSource.SALES,
        source_object=receipt,
        user=user,
    )
    receipt.save()
    return receipt


@transaction.atomic
def cancel_receipt(receipt: Receipt, reason: str, user) -> Receipt:
    receipt = Receipt.objects.select_for_update().get(pk=receipt.pk)
    if receipt.status == Receipt.Status.CANCELLED:
        raise ValidationError("この入金はすでに取消済みです。")
    reverse_journal(receipt.journal, max(datetime.date.today(), receipt.date), reason, user=user)
    receipt.status = Receipt.Status.CANCELLED
    receipt.save()
    record(Action.CANCEL, receipt, note=reason, user=user)
    return receipt
