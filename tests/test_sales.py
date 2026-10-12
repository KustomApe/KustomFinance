import datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.ledger.models import Account, JournalLine
from apps.masters.doc_services import issue_document, save_document
from apps.masters.documents import DocStatus, summarize_tax
from apps.masters.models import Item, Partner
from apps.sales.models import Delivery, Estimate, Invoice
from apps.sales.services import (
    cancel_invoice,
    cancel_receipt,
    create_receipt,
    invoice_from_deliveries,
    post_invoice,
)

D = datetime.date
pytestmark = pytest.mark.django_db


@pytest.fixture
def customer(db):
    return Partner.objects.create(
        code="C001", name="株式会社得意先", closing_day=0, payment_month_offset=1, payment_day=0
    )


def make_invoice(partner, lines, issue_date=None):
    inv = Invoice(partner=partner, issue_date=issue_date or D(2026, 5, 15), subject="テスト")
    return save_document(inv, lines)


def line(desc, qty, price, rate="10", **kw):
    return {
        "description": desc,
        "quantity": Decimal(qty),
        "unit_price": Decimal(price),
        "tax_rate": rate,
        **kw,
    }


@pytest.mark.parametrize(
    ("closing", "offset", "pay", "date", "expected"),
    [
        (0, 1, 0, D(2026, 5, 15), D(2026, 6, 30)),  # 月末締め翌月末払い
        (20, 1, 10, D(2026, 5, 20), D(2026, 6, 10)),  # 20日締め翌月10日
        (20, 1, 10, D(2026, 5, 21), D(2026, 7, 10)),  # 締日後は翌月締め
        (0, 2, 0, D(2026, 12, 1), D(2027, 2, 28)),  # 年またぎ・2月末
        (0, 0, 0, D(2026, 2, 3), D(2026, 2, 28)),
    ],
)
def test_due_date(closing, offset, pay, date, expected):
    p = Partner(closing_day=closing, payment_month_offset=offset, payment_day=pay)
    assert p.due_date_for(date) == expected


def test_tax_is_rounded_once_per_rate(customer):
    inv = make_invoice(
        customer, [line("A", 1, 105), line("B", 1, 105), line("C", 1, 105), line("食品", 3, 99.5, "8R")]
    )
    rows = {r.rate: r for r in inv.tax_rows()}
    assert rows["10"].base == 315 and rows["10"].tax == 31  # 行ごとに丸めると30円になる
    assert rows["8R"].base == 298 and rows["8R"].tax == 23  # 298.5 → 298（明細は切り捨て）, 23.84 → 23
    assert inv.total == 315 + 31 + 298 + 23


def test_summarize_respects_rounding_setting():
    class L:
        def __init__(self, amount, rate="10"):
            self.amount, self.tax_rate = Decimal(amount), rate

    assert summarize_tax([L(315)], "half_up")[0].tax == 32
    assert summarize_tax([L(315)], "ceil")[0].tax == 32
    assert summarize_tax([L(310)], "ceil")[0].tax == 31


def test_issue_invoice_posts_sales_journal(customer, fiscal_years, tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    inv = make_invoice(customer, [line("開発作業", 10, 50000), line("弁当", 20, 540, "8R")])
    inv = issue_document(inv, "pdf/invoice.html", on_issue=post_invoice)
    assert inv.status == DocStatus.ISSUED and inv.number == "INV-2026-00001"
    assert inv.due_date == D(2026, 6, 30)
    assert inv.pdf_file and len(inv.pdf_sha256) == 64
    assert inv.pdf_file.read(4) == b"%PDF"
    lines = list(JournalLine.objects.filter(journal=inv.journal).select_related("account"))
    by_acc = {}
    for ln in lines:
        by_acc[ln.account.name] = by_acc.get(ln.account.name, 0) + ln.amount
    assert by_acc["売掛金"] == inv.total == 500000 + 50000 + 10800 + 864
    assert by_acc["売上高"] == 510800
    assert by_acc["仮受消費税"] == 50864
    assert all(ln.partner_id == customer.pk for ln in lines)
    with pytest.raises(ValidationError):
        issue_document(inv, "pdf/invoice.html", on_issue=post_invoice)
    with pytest.raises(ValidationError, match="発行済み"):
        save_document(inv, [line("x", 1, 1)])


def test_item_specific_sales_account_and_tax_allocation(customer, fiscal_years, tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    misc = Account.objects.get(name="雑収入")
    item = Item.objects.create(code="X", name="手数料", sales_account=misc)
    inv = make_invoice(customer, [line("商品", 1, 1005), line("手数料", 1, 1005, item=item)])
    inv = issue_document(inv, "pdf/invoice.html", on_issue=post_invoice)
    credits = {ln.account.name: ln for ln in inv.journal.lines.filter(tax_base__isnull=True, side="C")}
    assert credits["売上高"].tax_amount + credits["雑収入"].tax_amount == 201  # 2010 * 10% = 201
    assert credits["売上高"].amount == 1005 and credits["雑収入"].amount == 1005


def test_cancel_invoice_reverses_journal(customer, fiscal_years, tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    from apps.masters.doc_services import cancel_document

    inv = issue_document(
        make_invoice(customer, [line("x", 1, 10000)]), "pdf/invoice.html", on_issue=post_invoice
    )
    cancel_document(inv, "金額誤り", on_cancel=cancel_invoice)
    inv.refresh_from_db()
    assert inv.status == DocStatus.CANCELLED
    assert inv.journal.is_reversed


def test_receipt_allocation_fee_and_advance(customer, fiscal_years, tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    inv1 = issue_document(
        make_invoice(customer, [line("a", 1, 100000)]), "pdf/invoice.html", on_issue=post_invoice
    )
    inv2 = issue_document(
        make_invoice(customer, [line("b", 1, 50000)]), "pdf/invoice.html", on_issue=post_invoice
    )
    bank = Account.by_key("bank")
    # 手数料660円を差し引かれて入金、inv1全額＋inv2一部、余りなし
    r = create_receipt(
        partner=customer,
        date=D(2026, 6, 30),
        deposit_account=bank,
        deposit_sub_account=None,
        amount=Decimal(149340),
        fee=Decimal(660),
        memo="",
        user=None,
        allocations=[(inv1, Decimal(110000)), (inv2, Decimal(40000))],
    )
    assert inv1.payment_status == "入金済" and inv2.payment_status == "一部入金"
    assert inv2.outstanding == 15000
    ar = Account.by_key("accounts_receivable")
    assert sum(ln.amount for ln in r.journal.lines.filter(account=ar)) == 150000
    with pytest.raises(ValidationError, match="消込額は 0〜15,000"):
        create_receipt(
            partner=customer,
            date=D(2026, 7, 1),
            deposit_account=bank,
            deposit_sub_account=None,
            amount=Decimal(20000),
            fee=Decimal(0),
            memo="",
            user=None,
            allocations=[(inv2, Decimal(20000))],
        )
    # 余剰は前受金
    r2 = create_receipt(
        partner=customer,
        date=D(2026, 7, 1),
        deposit_account=bank,
        deposit_sub_account=None,
        amount=Decimal(20000),
        fee=Decimal(0),
        memo="",
        user=None,
        allocations=[(inv2, Decimal(15000))],
    )
    assert r2.advance_amount == 5000
    assert r2.journal.lines.get(account__system_key="advances_received").amount == 5000
    from apps.masters.doc_services import cancel_document

    with pytest.raises(ValidationError, match="入金消込済み"):
        cancel_document(inv2, "x", on_cancel=cancel_invoice)
    cancel_receipt(r2, "誤登録", None)
    assert inv2.outstanding == 15000


def test_invoice_from_deliveries(customer, fiscal_years, tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    d1 = issue_document(
        save_document(Delivery(partner=customer, issue_date=D(2026, 5, 3)), [line("A", 1, 1000)]),
        "pdf/delivery.html",
    )
    d2 = issue_document(
        save_document(Delivery(partner=customer, issue_date=D(2026, 5, 20)), [line("B", 2, 500)]),
        "pdf/delivery.html",
    )
    inv = invoice_from_deliveries([d2, d1], None, D(2026, 5, 31))
    assert [ln.transaction_date for ln in inv.lines.all()] == [D(2026, 5, 3), D(2026, 5, 20)]
    assert inv.subtotal == 2000 and inv.tax_total == 200
    d1.refresh_from_db()
    assert d1.invoice == inv
    with pytest.raises(ValidationError, match="未請求"):
        invoice_from_deliveries([d1], None, D(2026, 5, 31))


def test_sales_flow_via_views(admin_client, customer, fiscal_years, tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    data = {
        "partner": customer.pk,
        "issue_date": "2026-05-01",
        "subject": "システム開発",
        "lines-TOTAL_FORMS": "2",
        "lines-INITIAL_FORMS": "0",
        "lines-MIN_NUM_FORMS": "0",
        "lines-MAX_NUM_FORMS": "300",
        "lines-0-description": "設計",
        "lines-0-quantity": "1",
        "lines-0-unit_price": "300000",
        "lines-0-tax_rate": "10",
        "lines-1-description": "",
        "lines-1-quantity": "",
        "lines-1-unit_price": "",
        "lines-1-tax_rate": "10",
    }
    resp = admin_client.post("/sales/estimates/new/", data)
    assert resp.status_code == 302, resp.content.decode()[:3000]
    est = Estimate.objects.get()
    assert est.total == 330000 and est.lines.count() == 1
    assert admin_client.get(f"/sales/estimates/{est.pk}/pdf/").status_code == 200
    admin_client.post(f"/sales/estimates/{est.pk}/issue/")
    resp = admin_client.post(f"/sales/estimates/{est.pk}/to-order/")
    order = est.orders.get()
    admin_client.post(f"/sales/orders/{order.pk}/issue/")
    admin_client.post(f"/sales/orders/{order.pk}/to-invoice/")
    inv = order.invoices.get()
    admin_client.post(f"/sales/invoices/{inv.pk}/issue/")
    inv.refresh_from_db()
    assert inv.status == DocStatus.ISSUED and inv.journal
    assert admin_client.get(f"/sales/invoices/{inv.pk}/pdf/").status_code == 200
    resp = admin_client.post(
        f"/sales/receipts/new/?partner={customer.pk}",
        {
            "partner": customer.pk,
            "date": "2026-06-30",
            "deposit_account": Account.by_key("bank").pk,
            "amount": "330000",
            "fee": "0",
            f"alloc-{inv.pk}": "330000",
        },
    )
    assert resp.status_code == 302, resp.content.decode()[:3000]
    assert inv.payment_status == "入金済"
    for url in [
        "/sales/estimates/",
        "/sales/orders/",
        "/sales/deliveries/",
        "/sales/invoices/",
        "/sales/billing/",
        "/sales/receipts/",
        "/sales/receivables/",
        "/sales/receivables/?format=csv",
        f"/sales/invoices/{inv.pk}/",
        "/masters/partners/",
        "/masters/items/",
        "/masters/departments/",
        "/masters/projects/",
        "/masters/partners/new/",
        f"/masters/partners/{customer.pk}/",
    ]:
        assert admin_client.get(url).status_code == 200, url


def test_viewer_cannot_create_documents(client, make_user):
    client.force_login(make_user("viewer", "viewer"))
    assert client.get("/sales/invoices/").status_code == 200
    assert client.get("/sales/invoices/new/").status_code == 403
    assert client.get("/masters/partners/new/").status_code == 403
