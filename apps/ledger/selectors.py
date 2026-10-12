"""残高・試算表・元帳の集計。

貸借対照表科目の残高は全期間の累計、損益計算書科目は事業年度内の累計とし、
前期以前の損益は繰越利益剰余金の期首残高に含める（決算振替仕訳は不要）。
"""

import datetime
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Q, Sum

from apps.core.models import Company, FiscalYear

from .models import PL_SECTIONS, SECTION_ORDER, Account, JournalLine, Section, Side

ZERO = Decimal(0)


def fiscal_year_start(date: datetime.date) -> datetime.date:
    fy = FiscalYear.for_date(date)
    if fy:
        return fy.start_date
    company = Company.load()
    return datetime.date(company.fiscal_year_of(date), company.fiscal_year_start_month, 1)


def _signed(account: Account, debit: Decimal, credit: Decimal) -> Decimal:
    """科目の通常の残高側をプラスとした残高。"""
    return debit - credit if account.normal_side == Side.DEBIT else credit - debit


def _sums(qs, condition: Q | None = None) -> dict:
    cond = condition or Q()
    return {
        "dr": Sum("amount", filter=cond & Q(side=Side.DEBIT), default=ZERO),
        "cr": Sum("amount", filter=cond & Q(side=Side.CREDIT), default=ZERO),
    }


def _opening_condition(date_from: datetime.date, fy_start: datetime.date) -> Q:
    pl = Q(account__section__in=PL_SECTIONS)
    return Q(journal__date__lt=date_from) & (~pl | Q(journal__date__gte=fy_start))


def prior_years_profit(fy_start: datetime.date, base_filter: Q | None = None) -> Decimal:
    """期首より前の損益累計（繰越利益剰余金へ振り替わる額）。"""
    sums = JournalLine.objects.filter(
        base_filter or Q(), account__section__in=PL_SECTIONS, journal__date__lt=fy_start
    ).aggregate(**_sums(None))
    return sums["cr"] - sums["dr"]


@dataclass
class BalanceRow:
    account: Account
    opening: Decimal = ZERO
    debit: Decimal = ZERO
    credit: Decimal = ZERO

    @property
    def closing(self) -> Decimal:
        return self.opening + _signed(self.account, self.debit, self.credit)

    @property
    def is_empty(self) -> bool:
        return not (self.opening or self.debit or self.credit)


@dataclass
class SectionGroup:
    section: str
    label: str
    rows: list[BalanceRow] = field(default_factory=list)

    @property
    def opening(self) -> Decimal:
        return sum((r.opening for r in self.rows), ZERO)

    @property
    def debit(self) -> Decimal:
        return sum((r.debit for r in self.rows), ZERO)

    @property
    def credit(self) -> Decimal:
        return sum((r.credit for r in self.rows), ZERO)

    @property
    def closing(self) -> Decimal:
        return sum((r.closing for r in self.rows), ZERO)


@dataclass
class TrialBalance:
    date_from: datetime.date
    date_to: datetime.date
    groups: list[SectionGroup]
    rows: list[BalanceRow]

    @property
    def total_debit(self) -> Decimal:
        return sum((r.debit for r in self.rows), ZERO)

    @property
    def total_credit(self) -> Decimal:
        return sum((r.credit for r in self.rows), ZERO)

    def closing_by_side(self, side: str) -> Decimal:
        """期末残高を借方残・貸方残に分けた合計（貸借一致の検証用）。"""
        total = ZERO
        for r in self.rows:
            amount = r.closing if r.account.normal_side == side else -r.closing
            total += amount
        return total


def trial_balance(
    date_from: datetime.date, date_to: datetime.date, include_empty: bool = False
) -> TrialBalance:
    fy_start = fiscal_year_start(date_from)
    opening_q = _opening_condition(date_from, fy_start)
    period_q = Q(journal__date__gte=date_from, journal__date__lte=date_to)
    agg = (
        JournalLine.objects.filter(journal__date__lte=date_to)
        .values("account_id")
        .annotate(
            open_dr=Sum("amount", filter=opening_q & Q(side=Side.DEBIT), default=ZERO),
            open_cr=Sum("amount", filter=opening_q & Q(side=Side.CREDIT), default=ZERO),
            dr=Sum("amount", filter=period_q & Q(side=Side.DEBIT), default=ZERO),
            cr=Sum("amount", filter=period_q & Q(side=Side.CREDIT), default=ZERO),
        )
    )
    by_account = {a["account_id"]: a for a in agg}
    carried = prior_years_profit(fy_start)
    rows = []
    for account in Account.objects.all():
        a = by_account.get(account.pk, {"open_dr": ZERO, "open_cr": ZERO, "dr": ZERO, "cr": ZERO})
        row = BalanceRow(account, _signed(account, a["open_dr"], a["open_cr"]), a["dr"], a["cr"])
        if account.system_key == "retained_earnings":
            row.opening += carried
        if include_empty or not row.is_empty:
            rows.append(row)
    rows.sort(key=lambda r: (SECTION_ORDER[r.account.section], r.account.code))
    groups: dict[str, SectionGroup] = {}
    for row in rows:
        section = row.account.section
        groups.setdefault(section, SectionGroup(section, Section(section).label)).rows.append(row)
    return TrialBalance(date_from, date_to, list(groups.values()), rows)


@dataclass
class LedgerEntry:
    line: JournalLine
    counterpart: str
    debit: Decimal
    credit: Decimal
    balance: Decimal


def counterpart_name(line: JournalLine, lines: list[JournalLine]) -> str:
    """相手科目。相手側の（消費税行を除く）科目が1つならその科目名、複数なら「諸口」。"""
    names = {other.account.name for other in lines if other.side != line.side and other.tax_base_id is None}
    if not names:
        names = {other.account.name for other in lines if other.side != line.side}
    return names.pop() if len(names) == 1 else "諸口"


def general_ledger(
    account: Account, date_from: datetime.date, date_to: datetime.date, sub_account=None, partner=None
) -> tuple[Decimal, list[LedgerEntry]]:
    base = Q(account=account)
    if sub_account:
        base &= Q(sub_account=sub_account)
    if partner:
        base &= Q(partner=partner)
    fy_start = fiscal_year_start(date_from)
    opening_sums = JournalLine.objects.filter(base & _opening_condition(date_from, fy_start)).aggregate(
        **_sums(None)
    )
    opening = _signed(account, opening_sums["dr"], opening_sums["cr"])
    if account.system_key == "retained_earnings" and not sub_account and not partner:
        opening += prior_years_profit(fy_start)
    lines = list(
        JournalLine.objects.filter(base, journal__date__gte=date_from, journal__date__lte=date_to)
        .select_related("journal", "tax_category", "sub_account")
        .order_by("journal__date", "journal__id", "line_no")
    )
    journal_ids = {line.journal_id for line in lines}
    siblings: dict[int, list[JournalLine]] = {}
    for other in JournalLine.objects.filter(journal_id__in=journal_ids).select_related("account"):
        siblings.setdefault(other.journal_id, []).append(other)
    balance = opening
    entries = []
    for line in lines:
        debit = line.amount if line.side == Side.DEBIT else ZERO
        credit = line.amount if line.side == Side.CREDIT else ZERO
        balance += _signed(account, debit, credit)
        entries.append(
            LedgerEntry(line, counterpart_name(line, siblings[line.journal_id]), debit, credit, balance)
        )
    return opening, entries
