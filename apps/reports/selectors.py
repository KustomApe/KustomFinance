"""決算書（損益計算書・貸借対照表）と消費税集計。"""

import datetime
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Q, Sum

from apps.ledger.models import (
    PL_SECTIONS,
    Account,
    AccountType,
    JournalLine,
    Section,
    Side,
    TaxCategory,
    TaxKind,
)
from apps.ledger.selectors import fiscal_year_start, trial_balance

ZERO = Decimal(0)


@dataclass
class Line:
    label: str
    amount: Decimal = ZERO
    compare: Decimal | None = None
    level: int = 1  # 0: 見出し・利益, 1: 区分合計, 2: 科目
    bold: bool = False


def _pl_amounts(date_from, date_to, department=None) -> dict[int, Decimal]:
    """損益科目ごとの期間発生額（収益は貸方、費用は借方をプラス）。"""
    qs = JournalLine.objects.filter(
        account__section__in=PL_SECTIONS, journal__date__gte=date_from, journal__date__lte=date_to
    )
    if department:
        qs = qs.filter(department=department)
    rows = qs.values("account_id").annotate(
        dr=Sum("amount", filter=Q(side=Side.DEBIT), default=ZERO),
        cr=Sum("amount", filter=Q(side=Side.CREDIT), default=ZERO),
    )
    accounts = {a.pk: a for a in Account.objects.filter(section__in=PL_SECTIONS)}
    result = {}
    for r in rows:
        account = accounts[r["account_id"]]
        result[r["account_id"]] = (
            r["cr"] - r["dr"] if account.account_type == AccountType.REVENUE else r["dr"] - r["cr"]
        )
    return result


def _year_before(d: datetime.date) -> datetime.date:
    if d.month == 2 and d.day == 29:
        return d.replace(year=d.year - 1, day=28)
    return d.replace(year=d.year - 1)


PL_STEPS = [
    (Section.SALES, "+", None),
    (Section.COST_OF_SALES, "-", "売上総利益"),
    (Section.SGA, "-", "営業利益"),
    (Section.NON_OPERATING_INCOME, "+", None),
    (Section.NON_OPERATING_EXPENSES, "-", "経常利益"),
    (Section.EXTRAORDINARY_INCOME, "+", None),
    (Section.EXTRAORDINARY_LOSSES, "-", "税引前当期純利益"),
    (Section.INCOME_TAXES, "-", "当期純利益"),
]


def profit_and_loss(date_from, date_to, department=None, compare: bool = False) -> list[Line]:
    current = _pl_amounts(date_from, date_to, department)
    previous = None
    if compare:
        previous = _pl_amounts(_year_before(date_from), _year_before(date_to), department)
    accounts = Account.objects.filter(section__in=PL_SECTIONS).order_by("code")
    lines: list[Line] = []
    profit, profit_prev = ZERO, ZERO
    for section, sign, subtotal_label in PL_STEPS:
        items = [
            a for a in accounts if a.section == section and (current.get(a.pk) or (previous or {}).get(a.pk))
        ]
        total = sum((current.get(a.pk, ZERO) for a in items), ZERO)
        total_prev = sum(((previous or {}).get(a.pk, ZERO) for a in items), ZERO)
        lines.append(Line(Section(section).label, level=0, bold=True))
        for a in items:
            lines.append(
                Line(
                    a.name, current.get(a.pk, ZERO), (previous or {}).get(a.pk, ZERO) if compare else None, 2
                )
            )
        lines.append(Line(f"{Section(section).label} 合計", total, total_prev if compare else None, 1))
        profit += total if sign == "+" else -total
        profit_prev += total_prev if sign == "+" else -total_prev
        if subtotal_label:
            lines.append(Line(subtotal_label, profit, profit_prev if compare else None, 0, True))
    return lines


@dataclass
class BalanceSheet:
    as_of: datetime.date
    assets: list[Line] = field(default_factory=list)
    liabilities: list[Line] = field(default_factory=list)
    total_assets: Decimal = ZERO
    total_liabilities_equity: Decimal = ZERO


def balance_sheet(as_of: datetime.date) -> BalanceSheet:
    fy_start = fiscal_year_start(as_of)
    tb = trial_balance(fy_start, as_of)
    by_section: dict[str, list] = {}
    net_income = ZERO
    for row in tb.rows:
        if row.account.section in PL_SECTIONS:
            net_income += row.closing if row.account.account_type == AccountType.REVENUE else -row.closing
        else:
            by_section.setdefault(row.account.section, []).append(row)
    bs = BalanceSheet(as_of)

    def block(target: list, sections, label: str, extra: list | None = None) -> Decimal:
        total = ZERO
        target.append(Line(label, level=0, bold=True))
        for section in sections:
            rows = [r for r in by_section.get(section, []) if r.closing]
            section_lines = [Line(r.account.name, r.closing, level=2) for r in rows]
            if section == Section.EQUITY and extra:
                section_lines += extra
            if not section_lines:
                continue
            subtotal = sum((ln.amount for ln in section_lines), ZERO)
            target.append(Line(Section(section).label, level=1, bold=True))
            target.extend(section_lines)
            target.append(Line(f"{Section(section).label} 合計", subtotal, level=1))
            total += subtotal
        target.append(Line(f"{label}合計", total, level=0, bold=True))
        return total

    bs.total_assets = block(
        bs.assets, [Section.CURRENT_ASSETS, Section.FIXED_ASSETS, Section.DEFERRED_ASSETS], "資産の部"
    )
    liabilities = block(
        bs.liabilities, [Section.CURRENT_LIABILITIES, Section.LONG_TERM_LIABILITIES], "負債の部"
    )
    equity = block(
        bs.liabilities,
        [Section.EQUITY],
        "純資産の部",
        extra=[Line("当期純利益", net_income, level=2)] if net_income else None,
    )
    bs.total_liabilities_equity = liabilities + equity
    bs.liabilities.append(Line("負債・純資産合計", bs.total_liabilities_equity, level=0, bold=True))
    return bs


@dataclass
class TaxRow:
    category: TaxCategory
    base: Decimal  # 税抜（控除できない税額を含む）
    tax: Decimal  # 計上した仮受・仮払消費税

    @property
    def gross(self) -> Decimal:
        return self.base + self.tax


@dataclass
class TaxSummary:
    sales: list[TaxRow]
    purchases: list[TaxRow]
    others: list[TaxRow]
    taxable_sales: Decimal = ZERO
    exempt_sales: Decimal = ZERO
    export_sales: Decimal = ZERO
    sales_tax: Decimal = ZERO
    purchase_tax: Decimal = ZERO
    sales_tax_by_rate: dict = field(default_factory=dict)  # rate -> (税込, 割戻し税額)

    @property
    def taxable_sales_ratio(self) -> Decimal | None:
        denominator = self.taxable_sales + self.export_sales + self.exempt_sales
        if not denominator:
            return None
        return (self.taxable_sales + self.export_sales) / denominator

    @property
    def net_tax(self) -> Decimal:
        return self.sales_tax - self.purchase_tax


NATIONAL_RATE = {10: Decimal("7.8"), 8: Decimal("6.24")}


def tax_summary(date_from, date_to) -> TaxSummary:
    """消費税集計表（申告書作成の参考）。売上は貸方、仕入は借方をプラスとする。"""
    rows = (
        JournalLine.objects.filter(
            journal__date__gte=date_from,
            journal__date__lte=date_to,
            tax_base__isnull=True,
            tax_category__isnull=False,
        )
        .values("tax_category_id")
        .annotate(
            base_dr=Sum("amount", filter=Q(side=Side.DEBIT), default=ZERO),
            base_cr=Sum("amount", filter=Q(side=Side.CREDIT), default=ZERO),
            tax_dr=Sum("tax_amount", filter=Q(side=Side.DEBIT), default=ZERO),
            tax_cr=Sum("tax_amount", filter=Q(side=Side.CREDIT), default=ZERO),
        )
    )
    categories = {t.pk: t for t in TaxCategory.objects.all()}
    summary = TaxSummary([], [], [])
    for r in rows:
        cat = categories[r["tax_category_id"]]
        if cat.kind in (TaxKind.TAXABLE_SALES, TaxKind.EXEMPT_SALES, TaxKind.EXPORT_SALES):
            row = TaxRow(cat, r["base_cr"] - r["base_dr"], r["tax_cr"] - r["tax_dr"])
            summary.sales.append(row)
            if cat.kind == TaxKind.TAXABLE_SALES:
                summary.taxable_sales += row.base
                summary.sales_tax += row.tax
                gross = summary.sales_tax_by_rate.get(cat.rate, ZERO) + row.gross
                summary.sales_tax_by_rate[cat.rate] = gross
            elif cat.kind == TaxKind.EXEMPT_SALES:
                summary.exempt_sales += row.base
            else:
                summary.export_sales += row.base
        elif cat.kind in (TaxKind.TAXABLE_PURCHASE, TaxKind.EXEMPT_PURCHASE):
            row = TaxRow(cat, r["base_dr"] - r["base_cr"], r["tax_dr"] - r["tax_cr"])
            summary.purchases.append(row)
            if cat.kind == TaxKind.TAXABLE_PURCHASE:
                summary.purchase_tax += row.tax
        elif r["base_dr"] or r["base_cr"]:
            summary.others.append(TaxRow(cat, r["base_dr"] - r["base_cr"], ZERO))
    summary.sales.sort(key=lambda r: r.category.sort_order)
    summary.purchases.sort(key=lambda r: r.category.sort_order)
    # 割戻し計算: 課税標準額（税込×100/110 等、千円未満切捨て）× 国税率
    summary.sales_tax_by_rate = {
        rate: (gross, ((gross * 100 / (100 + rate)) // 1000 * 1000), NATIONAL_RATE.get(rate, ZERO))
        for rate, gross in summary.sales_tax_by_rate.items()
    }
    return summary
