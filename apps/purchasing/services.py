import datetime
import hashlib
from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.audit.services import Action, record
from apps.core.models import Company
from apps.core.money import round_yen
from apps.core.numbering import next_number
from apps.ledger.models import Account, JournalSource, Side, TaxCategory
from apps.ledger.services import LineInput, post_journal, reverse_journal
from apps.masters.doc_services import LINE_FIELDS, allocate_tax, copy_document
from apps.masters.documents import DocStatus
from apps.masters.models import TaxRate

from .models import Bill, GoodsReceipt, Payment, PaymentAllocation

# 適格請求書発行事業者以外からの仕入に係る経過措置
TRANSITION_80_UNTIL = datetime.date(2026, 9, 30)
TRANSITION_50_UNTIL = datetime.date(2029, 9, 30)


def purchase_tax_code(rate: str, qualified: bool, date: datetime.date) -> str:
    base = {TaxRate.STANDARD: "P10", TaxRate.REDUCED: "P8R", TaxRate.EXEMPT: "PNT"}.get(rate, "OUT")
    if qualified or base not in ("P10", "P8R"):
        return base
    if date <= TRANSITION_80_UNTIL:
        return f"{base}-80"
    if date <= TRANSITION_50_UNTIL:
        return f"{base}-50"
    return f"{base}-0"


def file_sha256(field_file) -> str:
    digest = hashlib.sha256()
    field_file.open("rb")
    for chunk in field_file.chunks():
        digest.update(chunk)
    field_file.seek(0)
    return digest.hexdigest()


def post_bill(bill: Bill, user) -> None:
    """仕入請求書の計上: 仕入高・仮払消費税 / 買掛金。

    税額は請求書記載の額（税率ごと）を使い、登録番号のない仕入先は経過措置の控除割合を適用する
    （控除できない税額は仕入高などの取得価額に含める）。
    """
    if bill.total <= 0:
        raise ValidationError("合計金額が0円以下の仕入請求書は計上できません。")
    if not bill.supplier_registration_number:
        bill.supplier_registration_number = bill.partner.invoice_registration_number
    bill.purchase_date = bill.purchase_date or bill.issue_date
    bill.due_date = bill.due_date or bill.partner.due_date_for(bill.purchase_date)
    qualified = bool(bill.supplier_registration_number)
    default_account = bill.account or Account.by_key("purchases")
    bases: dict[str, dict] = defaultdict(lambda: defaultdict(Decimal))
    for line in bill.lines.select_related("item__purchase_account"):
        account = (line.item.purchase_account if line.item else None) or default_account
        bases[line.tax_rate][account] += line.amount
    taxes = {row.rate: row.tax for row in bill.tax_rows()}
    categories = {t.code: t for t in TaxCategory.objects.all()}
    rounding = Company.load().tax_rounding
    common = {"partner": bill.partner, "department": bill.department, "project": bill.project}
    lines = []
    for rate, groups in bases.items():
        category = categories[purchase_tax_code(rate, qualified, bill.purchase_date)]
        shares = allocate_tax(groups, taxes.get(rate, Decimal(0)))
        for account, base in groups.items():
            gross = base + shares[account]
            if gross == 0:
                continue
            deductible = round_yen(abs(shares[account]) * category.deductible_percent / 100, rounding)
            if not category.generates_tax_line:
                deductible = Decimal(0)
            lines.append(
                LineInput(
                    account,
                    Side.DEBIT if gross > 0 else Side.CREDIT,
                    abs(gross),
                    tax_category=category,
                    tax_amount=deductible,
                    **common,
                )
            )
    lines.append(LineInput(Account.by_key("accounts_payable"), Side.CREDIT, bill.total, **common))
    bill.journal = post_journal(
        bill.purchase_date,
        f"{bill.partner.name} 仕入 {bill.supplier_invoice_number or bill.number}",
        lines,
        source=JournalSource.PURCHASE,
        source_object=bill,
        user=user,
    )


def cancel_bill(bill: Bill, reason: str, user) -> None:
    if bill.allocations.exclude(payment__status=Payment.Status.CANCELLED).exists():
        raise ValidationError("支払消込済みの仕入請求書は取り消せません。先に支払を取り消してください。")
    if bill.journal:
        reverse_journal(bill.journal, max(datetime.date.today(), bill.journal.date), reason, user=user)
    bill.goods_receipts.update(bill=None)


@transaction.atomic
def bill_from_receipts(receipts: list[GoodsReceipt], user, issue_date: datetime.date) -> Bill:
    """複数の検収をまとめて仕入請求書の下書きを作成する（検収日を取引日として記載）。"""
    if not receipts:
        raise ValidationError("検収を選択してください。")
    if len({r.partner_id for r in receipts}) != 1:
        raise ValidationError("同じ仕入先の検収を選択してください。")
    if any(r.bill_id or r.status != DocStatus.ISSUED for r in receipts):
        raise ValidationError("発行済みで未計上の検収のみ選択できます。")
    receipts = sorted(receipts, key=lambda r: (r.issue_date, r.pk))
    first = receipts[0]
    bill = copy_document(
        first, Bill, user=user, line_date=first.issue_date, issue_date=issue_date, order=first.order
    )
    sort = bill.lines.count()
    for r in receipts[1:]:
        for line in r.lines.all():
            fields = {f: getattr(line, f) for f in LINE_FIELDS}
            bill.lines.create(**{**fields, "transaction_date": r.issue_date, "sort_order": sort})
            sort += 1
    bill.recalculate(Company.load().tax_rounding)
    bill.save()
    GoodsReceipt.objects.filter(pk__in=[r.pk for r in receipts]).update(bill=bill)
    return bill


@transaction.atomic
def create_payment(
    *,
    partner,
    date,
    pay_account,
    pay_sub_account,
    amount: Decimal,
    fee: Decimal,
    deduction: Decimal,
    memo: str,
    allocations: list[tuple[Bill, Decimal]],
    user,
) -> Payment:
    """支払を登録し、仕入請求書へ消し込む。

    仕訳: 買掛金（消込額）・前渡金（残額）・支払手数料（当社負担） / 預金（振込額＋手数料）・支払手数料（先方負担分）
    """
    allocations = [(b, a) for b, a in allocations if a]
    if amount <= 0:
        raise ValidationError("振込額を入力してください。")
    if fee < 0 or deduction < 0:
        raise ValidationError("手数料は0以上で入力してください。")
    errors = []
    amounts = {b.pk: a for b, a in allocations}
    for bill in Bill.objects.select_for_update().filter(pk__in=amounts):
        amt = amounts[bill.pk]
        if bill.partner_id != partner.pk or bill.status != DocStatus.ISSUED:
            errors.append(f"仕入請求書 {bill.number} は消込できません。")
        elif amt < 0 or amt > bill.outstanding:
            errors.append(
                f"仕入請求書 {bill.number} の消込額は 0〜{bill.outstanding:,} 円で入力してください。"
            )
    allocated = sum(a for _, a in allocations)
    if allocated > amount + deduction:
        errors.append(f"消込額の合計（{allocated:,}円）が振込額と先方負担手数料の合計を超えています。")
    if errors:
        raise ValidationError(errors)

    payment = Payment.objects.create(
        number=next_number("payment", date),
        date=date,
        partner=partner,
        pay_account=pay_account,
        pay_sub_account=pay_sub_account,
        amount=amount,
        fee=fee,
        deduction=deduction,
        memo=memo,
        created_by=user,
    )
    for bill, amt in allocations:
        PaymentAllocation.objects.create(payment=payment, bill=bill, amount=amt)
    common = {"partner": partner}
    p10 = TaxCategory.objects.get(code="P10")
    lines = []
    if allocated:
        lines.append(LineInput(Account.by_key("accounts_payable"), Side.DEBIT, allocated, **common))
    if amount + deduction - allocated:
        lines.append(
            LineInput(
                Account.by_key("advances_paid"),
                Side.DEBIT,
                amount + deduction - allocated,
                description="前渡金",
                **common,
            )
        )
    if fee:
        lines.append(
            LineInput(Account.by_key("fees"), Side.DEBIT, fee, p10, description="振込手数料", **common)
        )
    lines.append(LineInput(pay_account, Side.CREDIT, amount + fee, sub_account=pay_sub_account, **common))
    if deduction:
        lines.append(
            LineInput(
                Account.by_key("fees"),
                Side.CREDIT,
                deduction,
                p10,
                description="振込手数料（先方負担）",
                **common,
            )
        )
    payment.journal = post_journal(
        date,
        f"{partner.name} 支払 {payment.number}",
        lines,
        source=JournalSource.PURCHASE,
        source_object=payment,
        user=user,
    )
    payment.save()
    return payment


@transaction.atomic
def cancel_payment(payment: Payment, reason: str, user) -> Payment:
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if payment.status == Payment.Status.CANCELLED:
        raise ValidationError("この支払はすでに取消済みです。")
    reverse_journal(payment.journal, max(datetime.date.today(), payment.date), reason, user=user)
    payment.status = Payment.Status.CANCELLED
    payment.save()
    record(Action.CANCEL, payment, note=reason, user=user)
    return payment
