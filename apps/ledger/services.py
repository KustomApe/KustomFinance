"""仕訳の登録・取消。すべての取引（販売・購買・経費・銀行・償却）はここを経由して記帳する。"""

import datetime
from dataclasses import dataclass, field
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models, transaction

from apps.audit.context import current_user
from apps.audit.services import Action, record
from apps.core.models import Company, FiscalYear
from apps.core.money import round_yen
from apps.core.numbering import next_number

from .models import Account, Journal, JournalLine, JournalSource, Side, SubAccount, TaxCategory, TaxKind


@dataclass
class LineInput:
    """仕訳1行分の入力。amount は税込金額。

    tax_amount を省略すると税区分から自動計算する（内税・会社設定の端数処理）。
    請求書など税額が確定している場合は明示的に渡す。
    """

    account: Account
    side: str
    amount: Decimal
    tax_category: TaxCategory | None = None
    tax_amount: Decimal | None = None
    sub_account: SubAccount | None = None
    description: str = ""
    extra: dict = field(default_factory=dict)


def calc_included_tax(
    gross: Decimal, tax_category: TaxCategory | None, rounding: str | None = None
) -> Decimal:
    """税込金額に含まれる、仮払/仮受消費税として計上する税額。

    経過措置などで控除割合が100%未満の仕入は、控除できる部分のみを返す
    （控除できない部分は費用・資産の取得価額に含める）。
    """
    if not tax_category or not tax_category.generates_tax_line or gross == 0:
        return Decimal(0)
    rounding = rounding or Company.load().tax_rounding
    tax = Decimal(gross) * tax_category.rate / (100 + tax_category.rate)
    if tax_category.kind == TaxKind.TAXABLE_PURCHASE and tax_category.deductible_percent < 100:
        tax = tax * tax_category.deductible_percent / 100
    return round_yen(tax, rounding)


def ensure_open_period(date: datetime.date) -> None:
    fy = FiscalYear.for_date(date)
    if fy is None:
        raise ValidationError(f"{date:%Y/%m/%d} を含む会計期間が登録されていません。")
    if fy.is_closed:
        raise ValidationError(f"{fy.name} は決算締め済みのため記帳できません。")
    locked = Company.load().books_locked_through
    if locked and date <= locked:
        raise ValidationError(f"{locked:%Y/%m/%d} まで月次締め済みのため記帳できません。")


def _tax_account(tax_category: TaxCategory) -> Account:
    key = "tax_received" if tax_category.kind == TaxKind.TAXABLE_SALES else "tax_paid"
    return Account.by_key(key)


def _validate(lines: list[LineInput]) -> None:
    if len(lines) < 2:
        raise ValidationError("仕訳には2行以上の明細が必要です。")
    errors = []
    for i, line in enumerate(lines, 1):
        if line.amount <= 0:
            errors.append(f"{i}行目: 金額は1円以上で入力してください。")
        if not line.account.is_active:
            errors.append(f"{i}行目: 勘定科目「{line.account}」は無効です。")
        if line.sub_account and line.sub_account.account_id != line.account.pk:
            errors.append(
                f"{i}行目: 補助科目「{line.sub_account.name}」は「{line.account}」の補助科目ではありません。"
            )
        if line.tax_amount is not None and abs(line.tax_amount) > line.amount:
            errors.append(f"{i}行目: 消費税額が金額を超えています。")
    if errors:
        raise ValidationError(errors)
    debit = sum(line.amount for line in lines if line.side == Side.DEBIT)
    credit = sum(line.amount for line in lines if line.side == Side.CREDIT)
    if debit != credit:
        raise ValidationError(f"貸借が一致しません（借方 {debit:,} / 貸方 {credit:,}）。")


@transaction.atomic
def post_journal(
    date: datetime.date,
    description: str,
    lines: list[LineInput],
    *,
    source: str = JournalSource.MANUAL,
    source_object: models.Model | None = None,
    reverses: Journal | None = None,
    user=None,
) -> Journal:
    ensure_open_period(date)
    _validate(lines)
    rounding = Company.load().tax_rounding
    journal = Journal.objects.create(
        number=next_number("journal", date),
        date=date,
        description=description,
        source=source,
        source_type=ContentType.objects.get_for_model(source_object) if source_object else None,
        source_id=source_object.pk if source_object else None,
        reverses=reverses,
        created_by=user or current_user.get(),
    )
    line_no = 0
    for line in lines:
        tax = (
            line.tax_amount
            if line.tax_amount is not None
            else calc_included_tax(line.amount, line.tax_category, rounding)
        )
        line_no += 1
        base = JournalLine.objects.create(
            journal=journal,
            line_no=line_no,
            side=line.side,
            account=line.account,
            sub_account=line.sub_account,
            amount=line.amount - tax,
            tax_category=line.tax_category,
            tax_amount=tax,
            description=line.description or description,
        )
        if tax:
            line_no += 1
            JournalLine.objects.create(
                journal=journal,
                line_no=line_no,
                side=line.side,
                account=_tax_account(line.tax_category),
                amount=tax,
                tax_base=base,
                description=line.description or description,
            )
    return journal


@transaction.atomic
def reverse_journal(journal: Journal, date: datetime.date, reason: str, *, user=None) -> Journal:
    """取消仕訳（赤伝）を登録する。元の仕訳の貸借を入れ替えて同額を計上する。"""
    journal = Journal.objects.select_for_update().get(pk=journal.pk)
    if journal.is_reversed:
        raise ValidationError("この仕訳はすでに取消済みです。")
    if journal.reverses_id:
        raise ValidationError("取消仕訳はさらに取り消せません。")
    if not reason.strip():
        raise ValidationError("取消理由を入力してください。")
    lines = [
        LineInput(
            account=line.account,
            side=Side.CREDIT if line.side == Side.DEBIT else Side.DEBIT,
            amount=line.gross_amount,
            tax_category=line.tax_category,
            tax_amount=line.tax_amount,
            sub_account=line.sub_account,
            description=line.description,
        )
        for line in journal.lines.filter(tax_base__isnull=True).select_related("account", "tax_category")
    ]
    reversal = post_journal(
        date,
        f"【取消】{journal.number} {reason}",
        lines,
        source=JournalSource.REVERSAL,
        source_object=journal.source_object,
        reverses=journal,
        user=user,
    )
    record(Action.CANCEL, journal, note=f"取消仕訳 {reversal.number}: {reason}", user=user)
    return reversal
