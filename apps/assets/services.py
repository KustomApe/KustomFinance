"""減価償却の計算と計上（直接法）。

- 月割: 事業供用月は1か月として数える。
- 端数: 償却額の1円未満は切り捨て。
- 定額法・定率法は備忘価額1円を残す。一括償却資産・少額減価償却資産は全額を償却する。
"""

import calendar
import datetime
from collections import defaultdict
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum

from apps.audit.services import Action, record
from apps.core.models import Company, FiscalYear
from apps.ledger.models import Account, JournalSource, Side
from apps.ledger.services import LineInput, post_journal

from .models import DepreciationEntry, DepreciationRate, FixedAsset

Method = FixedAsset.Method
ZERO = Decimal(0)


def _floor(value) -> Decimal:
    return Decimal(value).quantize(Decimal(1), rounding=ROUND_FLOOR)


def _month_index(d: datetime.date) -> int:
    return d.year * 12 + d.month - 1


def months_between(start: datetime.date, end: datetime.date) -> int:
    """start の月から end の月まで（両端を含む）の月数。"""
    return max(0, _month_index(end) - _month_index(start) + 1)


def month_end(d: datetime.date) -> datetime.date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def fiscal_bounds(date: datetime.date) -> tuple[datetime.date, datetime.date]:
    fy = FiscalYear.for_date(date)
    if fy:
        return fy.start_date, fy.end_date
    company = Company.load()
    start = datetime.date(company.fiscal_year_of(date), company.fiscal_year_start_month, 1)
    nxt = datetime.date(start.year + 1, start.month, 1)
    return start, nxt - datetime.timedelta(days=1)


def _floor_value(asset: FixedAsset) -> Decimal:
    return Decimal(1) if asset.method in (Method.STRAIGHT_LINE, Method.DECLINING) else ZERO


@dataclass
class YearPlan:
    fy_start: datetime.date
    fy_end: datetime.date
    opening_book_value: Decimal
    amount: Decimal
    service_months: int  # 期中で償却対象となる月数
    switched_base: Decimal | None = None  # この年度に改定償却率へ切り替えた場合の改定取得価額

    @property
    def closing_book_value(self) -> Decimal:
        return self.opening_book_value - self.amount


def plan_for_year(
    asset: FixedAsset, fy_start, fy_end, opening_bv: Decimal, revised_base: Decimal | None
) -> YearPlan:
    """その事業年度の償却額（年額）を求める。"""
    start = max(fy_start, asset.service_date.replace(day=1))
    service_months = months_between(start, fy_end) if asset.service_date <= fy_end else 0
    fy_months = months_between(fy_start, fy_end)
    plan = YearPlan(fy_start, fy_end, opening_bv, ZERO, service_months)
    limit = opening_bv - _floor_value(asset)
    if service_months == 0 or limit <= 0 or asset.method == Method.NONE:
        return plan
    cost = asset.acquisition_cost
    if asset.method == Method.IMMEDIATE:
        plan.amount = limit
        return plan
    if asset.method == Method.LUMP_SUM:
        plan.amount = min(limit, _floor(cost * fy_months / 36))
        return plan
    if not asset.useful_life:
        raise ValidationError(f"{asset}: 耐用年数を入力してください。")
    rate = DepreciationRate.objects.filter(useful_life=asset.useful_life).first()
    if rate is None:
        raise ValidationError(f"耐用年数{asset.useful_life}年の償却率が登録されていません。")
    if asset.method == Method.STRAIGHT_LINE:
        annual = cost * rate.straight_line_rate
    else:
        annual = opening_bv * rate.declining_rate
        if revised_base is not None:
            annual = revised_base * rate.revised_rate
        elif annual < cost * rate.guarantee_rate:
            plan.switched_base = opening_bv
            annual = opening_bv * rate.revised_rate
    plan.amount = min(limit, _floor(annual * service_months / 12))
    return plan


def opening_book_value(asset: FixedAsset, fy_start: datetime.date) -> Decimal:
    posted = asset.entries.filter(fiscal_year_start__lt=fy_start).aggregate(s=Sum("amount", default=ZERO))[
        "s"
    ]
    return asset.acquisition_cost - asset.opening_accumulated - posted


def projected_schedule(asset: FixedAsset, years: int = 60) -> list[YearPlan]:
    """事業供用日（移行資産は基準日）からの償却予定表。"""
    start_date = asset.opening_date or asset.service_date
    bv = asset.acquisition_cost - asset.opening_accumulated
    revised = asset.revised_base
    plans = []
    fy_start, fy_end = fiscal_bounds(start_date)
    for _ in range(years):
        plan = plan_for_year(asset, fy_start, fy_end, bv, revised)
        if plan.switched_base is not None:
            revised = plan.switched_base
        if asset.disposal_date and asset.disposal_date <= fy_end:
            plan.amount = target_through(plan, asset, asset.disposal_date)
            plans.append(plan)
            break
        plans.append(plan)
        bv = plan.closing_book_value
        if bv <= _floor_value(asset) or asset.method == Method.NONE:
            break
        fy_start = fy_end + datetime.timedelta(days=1)
        fy_end = datetime.date(fy_start.year + 1, fy_start.month, 1) - datetime.timedelta(days=1)
    return plans


def target_through(plan: YearPlan, asset: FixedAsset, through: datetime.date) -> Decimal:
    """事業年度の期首から through までに計上すべき償却額の累計（月割）。"""
    if plan.amount == 0 or through < plan.fy_start:
        return ZERO
    through = min(through, plan.fy_end)
    if asset.method == Method.IMMEDIATE:
        return plan.amount if through >= asset.service_date.replace(day=1) else ZERO
    if asset.method == Method.LUMP_SUM:
        total, elapsed = months_between(plan.fy_start, plan.fy_end), months_between(plan.fy_start, through)
    else:
        start = max(plan.fy_start, asset.service_date.replace(day=1))
        total, elapsed = plan.service_months, months_between(start, through)
    if elapsed >= total:
        return plan.amount
    return _floor(plan.amount * elapsed / total)


@dataclass
class RunRow:
    asset: FixedAsset
    plan: YearPlan
    target: Decimal
    posted: Decimal

    @property
    def amount(self) -> Decimal:
        return max(ZERO, self.target - self.posted)


def preview(through: datetime.date, assets=None) -> list[RunRow]:
    fy_start, fy_end = fiscal_bounds(through)
    if assets is None:
        assets = (
            FixedAsset.objects.exclude(method=Method.NONE)
            .filter(service_date__lte=through)
            .exclude(disposal_date__lt=fy_start)
        )
    rows = []
    for asset in (
        assets.select_related("account", "department") if hasattr(assets, "select_related") else assets
    ):
        plan = plan_for_year(asset, fy_start, fy_end, opening_book_value(asset, fy_start), asset.revised_base)
        limit_date = min(through, asset.disposal_date) if asset.disposal_date else through
        posted = asset.entries.filter(fiscal_year_start=fy_start).aggregate(s=Sum("amount", default=ZERO))[
            "s"
        ]
        rows.append(RunRow(asset, plan, target_through(plan, asset, limit_date), posted))
    return rows


@transaction.atomic
def run_depreciation(through: datetime.date, user=None, assets=None):
    """through（月末）までの償却額を計上する。計上済みの額との差額だけを計上するため、何度実行してもよい。"""
    rows = [r for r in preview(through, assets) if r.amount > 0]
    if not rows:
        return None
    expense = Account.by_key("depreciation")
    debit: dict = defaultdict(Decimal)
    credit: dict = defaultdict(Decimal)
    for r in rows:
        debit[r.asset.department] += r.amount
        credit[r.asset.account] += r.amount
    lines = [LineInput(expense, Side.DEBIT, amt, department=dept) for dept, amt in debit.items()]
    lines += [LineInput(account, Side.CREDIT, amt) for account, amt in credit.items()]
    journal = post_journal(
        through, f"減価償却費 {through:%Y年%m月}まで", lines, source=JournalSource.ASSET, user=user
    )
    fy_start, _ = fiscal_bounds(through)
    for r in rows:
        DepreciationEntry.objects.create(
            asset=r.asset,
            fiscal_year_start=fy_start,
            date=through,
            amount=r.amount,
            journal=journal,
            created_by=user,
        )
        if r.plan.switched_base is not None and r.asset.revised_base is None:
            r.asset.revised_base = r.plan.switched_base
            r.asset.save(update_fields=["revised_base"])
    return journal


@transaction.atomic
def dispose(asset: FixedAsset, date: datetime.date, reason: str, user=None) -> FixedAsset:
    """除却: 除却月までの償却を計上し、残りの帳簿価額を固定資産除却損とする。"""
    asset = FixedAsset.objects.select_for_update().get(pk=asset.pk)
    if asset.status == FixedAsset.Status.DISPOSED:
        raise ValidationError("すでに除却済みです。")
    if date < asset.service_date:
        raise ValidationError("除却日は事業供用日以降にしてください。")
    asset.disposal_date = date
    if asset.method != Method.NONE:
        run_depreciation(date, user, assets=[asset])
    bv = asset.book_value
    if bv > 0:
        asset.disposal_journal = post_journal(
            date,
            f"固定資産除却 {asset} {reason}",
            [
                LineInput(Account.by_key("disposal_loss"), Side.DEBIT, bv, department=asset.department),
                LineInput(asset.account, Side.CREDIT, bv),
            ],
            source=JournalSource.ASSET,
            source_object=asset,
            user=user,
        )
    asset.status = FixedAsset.Status.DISPOSED
    asset.save()
    record(Action.OTHER, asset, note=f"除却: {reason}", user=user)
    return asset
