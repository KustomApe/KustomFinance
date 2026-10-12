import datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import connection

from apps.core.models import Company
from apps.ledger.models import Account, JournalLine, Side, TaxCategory
from apps.ledger.selectors import general_ledger, trial_balance
from apps.ledger.services import LineInput, calc_included_tax, post_journal, reverse_journal

D = datetime.date
pytestmark = pytest.mark.django_db


def acc(key_or_name):
    return Account.objects.filter(system_key=key_or_name).first() or Account.objects.get(name=key_or_name)


def tax(code):
    return TaxCategory.objects.get(code=code)


def immediate_constraints():
    with connection.cursor() as c:
        c.execute("SET CONSTRAINTS ALL IMMEDIATE")


@pytest.mark.parametrize(
    ("gross", "code", "rounding", "expected"),
    [
        (11000, "P10", "floor", 1000),
        (10800, "P8R", "floor", 800),
        (1099, "P10", "floor", 99),  # 99.909...
        (1099, "P10", "half_up", 100),
        (11000, "P10-80", "floor", 800),
        (11000, "P10-50", "floor", 500),
        (11000, "P10-0", "floor", 0),
        (11000, "OUT", "floor", 0),
        (11000, "PNT", "floor", 0),
    ],
)
def test_calc_included_tax(gross, code, rounding, expected):
    assert calc_included_tax(Decimal(gross), tax(code), rounding) == expected


def test_post_journal_splits_consumption_tax(fiscal_years):
    j = post_journal(
        D(2026, 5, 10),
        "文房具",
        [
            LineInput(acc("消耗品費"), Side.DEBIT, Decimal(11000), tax("P10")),
            LineInput(acc("bank"), Side.CREDIT, Decimal(11000), tax("OUT")),
        ],
    )
    immediate_constraints()
    lines = {(ln.account.name, ln.side): ln for ln in j.lines.all()}
    assert lines[("消耗品費", "D")].amount == 10000
    assert lines[("消耗品費", "D")].tax_amount == 1000
    assert lines[("仮払消費税", "D")].amount == 1000
    assert lines[("普通預金", "C")].amount == 11000
    assert j.number == "JE-2026-00001"


def test_sales_tax_goes_to_tax_received(fiscal_years):
    j = post_journal(
        D(2026, 5, 10),
        "売上",
        [
            LineInput(acc("accounts_receivable"), Side.DEBIT, Decimal(110000)),
            LineInput(acc("sales"), Side.CREDIT, Decimal(110000), tax("S10")),
        ],
    )
    assert j.lines.get(account__system_key="tax_received").amount == 10000


def test_explicit_tax_amount_is_used(fiscal_years):
    j = post_journal(
        D(2026, 5, 10),
        "請求書",
        [
            LineInput(acc("accounts_receivable"), Side.DEBIT, Decimal(1099)),
            LineInput(acc("sales"), Side.CREDIT, Decimal(1099), tax("S10"), tax_amount=Decimal(100)),
        ],
    )
    assert j.lines.get(account__system_key="tax_received").amount == 100


def test_unbalanced_journal_rejected(fiscal_years):
    with pytest.raises(ValidationError, match="貸借が一致しません"):
        post_journal(
            D(2026, 5, 10),
            "x",
            [
                LineInput(acc("cash"), Side.DEBIT, Decimal(100)),
                LineInput(acc("sales"), Side.CREDIT, Decimal(90)),
            ],
        )


def test_db_trigger_rejects_unbalanced_lines(fiscal_years):
    j = post_journal(
        D(2026, 5, 10),
        "x",
        [
            LineInput(acc("cash"), Side.DEBIT, Decimal(100)),
            LineInput(acc("capital"), Side.CREDIT, Decimal(100)),
        ],
    )
    JournalLine.objects.create(journal=j, line_no=99, side=Side.DEBIT, account=acc("cash"), amount=1)
    with pytest.raises(Exception, match="貸借が一致しません"):
        immediate_constraints()


def test_journal_is_immutable(fiscal_years):
    j = post_journal(
        D(2026, 5, 10),
        "x",
        [
            LineInput(acc("cash"), Side.DEBIT, Decimal(100)),
            LineInput(acc("capital"), Side.CREDIT, Decimal(100)),
        ],
    )
    with pytest.raises(Exception, match="変更・削除できません"):
        JournalLine.objects.filter(journal=j).update(amount=200)


def test_period_checks(fiscal_years):
    lines = [
        LineInput(acc("cash"), Side.DEBIT, Decimal(100)),
        LineInput(acc("capital"), Side.CREDIT, Decimal(100)),
    ]
    with pytest.raises(ValidationError, match="会計期間が登録されていません"):
        post_journal(D(2030, 1, 1), "x", lines)
    company = Company.load()
    company.books_locked_through = D(2026, 4, 30)
    company.save()
    with pytest.raises(ValidationError, match="月次締め済み"):
        post_journal(D(2026, 4, 30), "x", lines)
    post_journal(D(2026, 5, 1), "x", lines)
    fiscal_years[0].is_closed = True
    fiscal_years[0].save()
    company.books_locked_through = None
    company.save()
    with pytest.raises(ValidationError, match="決算締め済み"):
        post_journal(D(2026, 3, 1), "x", lines)


def test_reverse_journal(fiscal_years):
    j = post_journal(
        D(2026, 5, 10),
        "文房具",
        [
            LineInput(acc("消耗品費"), Side.DEBIT, Decimal(11000), tax("P10")),
            LineInput(acc("bank"), Side.CREDIT, Decimal(11000)),
        ],
    )
    r = reverse_journal(j, D(2026, 5, 11), "金額誤り")
    immediate_constraints()
    j.refresh_from_db()
    assert j.is_reversed and r.reverses == j
    tb = trial_balance(D(2026, 4, 1), D(2026, 5, 31))
    assert all(row.closing == 0 for row in tb.rows)
    with pytest.raises(ValidationError, match="取消済み"):
        reverse_journal(j, D(2026, 5, 11), "again")


def test_trial_balance_and_retained_earnings_carry_forward(fiscal_years):
    post_journal(
        D(2025, 4, 1),
        "資本金",
        [
            LineInput(acc("bank"), Side.DEBIT, Decimal(1_000_000)),
            LineInput(acc("capital"), Side.CREDIT, Decimal(1_000_000)),
        ],
    )
    post_journal(
        D(2025, 6, 1),
        "売上",
        [
            LineInput(acc("bank"), Side.DEBIT, Decimal(550_000)),
            LineInput(acc("sales"), Side.CREDIT, Decimal(550_000), tax("S10")),
        ],
    )
    post_journal(
        D(2025, 7, 1),
        "家賃",
        [
            LineInput(acc("地代家賃"), Side.DEBIT, Decimal(110_000), tax("P10")),
            LineInput(acc("bank"), Side.CREDIT, Decimal(110_000)),
        ],
    )
    post_journal(
        D(2026, 4, 10),
        "売上",
        [
            LineInput(acc("bank"), Side.DEBIT, Decimal(220_000)),
            LineInput(acc("sales"), Side.CREDIT, Decimal(220_000), tax("S10")),
        ],
    )
    immediate_constraints()

    first = trial_balance(D(2025, 4, 1), D(2026, 3, 31))
    rows = {r.account.name: r for r in first.rows}
    assert rows["売上高"].closing == 500_000
    assert rows["地代家賃"].closing == 100_000
    assert first.total_debit == first.total_credit

    second = trial_balance(D(2026, 4, 1), D(2027, 3, 31))
    rows = {r.account.name: r for r in second.rows}
    assert rows["繰越利益剰余金"].opening == 400_000  # 前期利益 500,000 - 100,000
    assert rows["売上高"].opening == 0 and rows["売上高"].closing == 200_000
    assert rows["普通預金"].opening == 1_440_000
    assert rows["仮受消費税"].closing == 70_000
    assert second.closing_by_side(Side.DEBIT) == second.closing_by_side(Side.CREDIT)

    opening, entries = general_ledger(acc("bank"), D(2026, 4, 1), D(2026, 4, 30))
    assert opening == 1_440_000
    assert entries[-1].balance == 1_660_000
    assert entries[0].counterpart == "売上高"


def test_journal_entry_view(admin_client, fiscal_years):
    data = {
        "date": "2026-05-10",
        "description": "備品購入",
        "rows-TOTAL_FORMS": "1",
        "rows-INITIAL_FORMS": "0",
        "rows-MIN_NUM_FORMS": "1",
        "rows-MAX_NUM_FORMS": "200",
        "rows-0-debit_account": acc("消耗品費").pk,
        "rows-0-debit_tax_category": tax("P10").pk,
        "rows-0-debit_amount": "5500",
        "rows-0-credit_account": acc("cash").pk,
        "rows-0-credit_amount": "5500",
    }
    resp = admin_client.post("/ledger/journals/new/", data)
    assert resp.status_code == 302, resp.content.decode()[:2000]
    for url in [
        "/ledger/journals/",
        "/ledger/trial-balance/",
        "/ledger/general-ledger/",
        resp.url,
        "/ledger/accounts/",
        "/ledger/tax-categories/",
        "/ledger/closing/",
        f"/ledger/journals/new/?copy={resp.url.strip('/').split('/')[-1]}",
        "/ledger/journals/?format=csv",
        "/ledger/trial-balance/?format=csv",
    ]:
        assert admin_client.get(url, follow=True).status_code == 200, url

    data["rows-0-credit_amount"] = "5000"
    resp = admin_client.post("/ledger/journals/new/", data)
    assert "貸借が一致しません" in resp.content.decode()


def test_sales_role_cannot_post_journal(client, make_user):
    client.force_login(make_user("eigyo", "sales"))
    assert client.get("/ledger/journals/new/").status_code == 403
    assert client.get("/ledger/journals/").status_code == 200


def test_reverse_via_view(admin_client, fiscal_years):
    j = post_journal(
        D(2026, 5, 10),
        "x",
        [
            LineInput(acc("cash"), Side.DEBIT, Decimal(100)),
            LineInput(acc("capital"), Side.CREDIT, Decimal(100)),
        ],
    )
    resp = admin_client.post(f"/ledger/journals/{j.pk}/", {"date": "2026-05-11", "reason": "重複登録"})
    assert resp.status_code == 302
    j.refresh_from_db()
    assert j.is_reversed
    assert "重複登録" in j.reversed_by.description
