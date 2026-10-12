import datetime
from decimal import Decimal

import pytest

from apps.assets import services
from apps.assets.models import FixedAsset
from apps.assets.rates import declining_rates, straight_line_rate
from apps.core.models import FiscalYear
from apps.ledger.models import Account

D = datetime.date
pytestmark = pytest.mark.django_db
M = FixedAsset.Method


def make_asset(**kw):
    defaults = {
        "number": f"FA-{FixedAsset.objects.count() + 1}",
        "name": "PC",
        "account": Account.objects.get(name="工具器具備品"),
        "acquisition_date": D(2026, 4, 1),
        "service_date": D(2026, 4, 1),
        "acquisition_cost": Decimal(1_000_000),
        "method": M.STRAIGHT_LINE,
        "useful_life": 5,
    }
    return FixedAsset.objects.create(**{**defaults, **kw})


@pytest.fixture
def years(fiscal_years):
    for y in range(2027, 2034):
        FiscalYear.objects.get_or_create(
            start_date=D(y, 4, 1), defaults={"name": f"{y}", "end_date": D(y + 1, 3, 31)}
        )


def test_rates():
    assert straight_line_rate(5) == Decimal("0.200") and straight_line_rate(6) == Decimal("0.167")
    assert declining_rates(5) == (Decimal("0.400"), Decimal("0.500"), Decimal("0.10800"))
    assert declining_rates(10)[:2] == (Decimal("0.200"), Decimal("0.250"))


def test_straight_line_schedule(years):
    asset = make_asset(service_date=D(2026, 10, 10))
    plans = services.projected_schedule(asset)
    assert [p.amount for p in plans] == [100000, 200000, 200000, 200000, 200000, 99999]
    assert plans[0].service_months == 6
    assert plans[-1].closing_book_value == 1


def test_declining_balance_switches_to_revised_rate(years):
    asset = make_asset(method=M.DECLINING)
    plans = services.projected_schedule(asset)
    assert [p.amount for p in plans] == [400000, 240000, 144000, 108000, 107999]


def test_lump_sum_and_immediate(years):
    lump = make_asset(
        method=M.LUMP_SUM, acquisition_cost=Decimal(150000), service_date=D(2027, 2, 1), useful_life=None
    )
    assert [p.amount for p in services.projected_schedule(lump)] == [50000, 50000, 50000]
    small = make_asset(
        method=M.IMMEDIATE, acquisition_cost=Decimal(250000), service_date=D(2026, 12, 1), useful_life=None
    )
    assert [p.amount for p in services.projected_schedule(small)] == [250000]


def test_monthly_run_is_idempotent(years):
    asset = make_asset(service_date=D(2026, 10, 10))
    j1 = services.run_depreciation(D(2026, 10, 31))
    assert asset.entries.get().amount == 16666  # 100,000 × 1/6
    assert services.run_depreciation(D(2026, 10, 31)) is None
    services.run_depreciation(D(2026, 11, 30))
    assert asset.posted_total == 33333
    services.run_depreciation(D(2027, 3, 31))
    assert asset.posted_total == 100000
    lines = {(ln.account.name, ln.side): ln.amount for ln in j1.lines.select_related("account")}
    assert lines == {("減価償却費", "D"): 16666, ("工具器具備品", "C"): 16666}
    services.run_depreciation(D(2027, 4, 30))
    assert asset.posted_total == 100000 + 16666  # 翌年度 200,000 × 1/12


def test_declining_switch_is_persisted(years):
    asset = make_asset(method=M.DECLINING)
    for y in (2027, 2028, 2029, 2030):
        services.run_depreciation(D(y, 3, 31))
    asset.refresh_from_db()
    assert asset.revised_base == 216000
    services.run_depreciation(D(2031, 3, 31))
    assert asset.book_value == 1


def test_dispose(years):
    asset = make_asset(service_date=D(2026, 4, 1))
    services.dispose(asset, D(2026, 9, 15), "故障")
    asset.refresh_from_db()
    assert asset.posted_total == 100000  # 4〜9月の6か月分
    assert asset.status == "disposed" and asset.book_value == 900000
    loss = asset.disposal_journal.lines.get(side="D")
    assert loss.account.name == "固定資産除却損" and loss.amount == 900000


def test_opening_accumulated(years):
    asset = make_asset(
        service_date=D(2023, 4, 1), opening_date=D(2026, 4, 1), opening_accumulated=Decimal(600000)
    )
    plans = services.projected_schedule(asset)
    assert [p.amount for p in plans] == [200000, 199999]


def test_asset_views(admin_client, years):
    resp = admin_client.post(
        "/assets/new/",
        {
            "name": "サーバー",
            "account": Account.objects.get(name="工具器具備品").pk,
            "acquisition_date": "2026-05-01",
            "service_date": "2026-05-10",
            "acquisition_cost": "600000",
            "quantity": "1",
            "method": "straight_line",
            "useful_life": "5",
            "opening_accumulated": "0",
        },
    )
    assert resp.status_code == 302, resp.content.decode()[:2000]
    asset = FixedAsset.objects.get()
    assert asset.number == "FA-2026-00001"
    resp = admin_client.post(
        "/assets/new/",
        {
            "name": "高額",
            "account": Account.objects.get(name="工具器具備品").pk,
            "acquisition_date": "2026-05-01",
            "service_date": "2026-05-10",
            "acquisition_cost": "500000",
            "quantity": "1",
            "method": "immediate",
            "opening_accumulated": "0",
        },
    )
    assert "30万円未満" in resp.content.decode()
    assert admin_client.get("/assets/depreciation/?through=2026-06-15").status_code == 200
    admin_client.post("/assets/depreciation/", {"through": "2026-06-30"})
    assert asset.posted_total == 20000  # 120,000 × 2/11
    for url in [
        "/assets/",
        "/assets/?format=csv",
        f"/assets/{asset.pk}/",
        "/assets/rates/",
        f"/assets/{asset.pk}/edit/",
    ]:
        assert admin_client.get(url).status_code == 200, url
