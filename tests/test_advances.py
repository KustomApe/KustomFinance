import datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.ledger.models import Account
from apps.masters.advances import PURCHASE, SALES, apply_advance, cancel_application
from apps.masters.doc_services import cancel_document, issue_document, save_document
from apps.masters.models import Partner
from apps.purchasing.models import Bill
from apps.purchasing.services import cancel_payment, create_payment, post_bill
from apps.sales.models import Invoice
from apps.sales.services import cancel_invoice, cancel_receipt, create_receipt, post_invoice

D = datetime.date
JUNE_1 = datetime.date(2026, 6, 1)
pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def media(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def customer(db):
    return Partner.objects.create(code="C1", name="株式会社前受")


@pytest.fixture
def supplier(db):
    return Partner.objects.create(
        code="S1",
        name="株式会社前渡",
        is_customer=False,
        is_supplier=True,
        invoice_registration_number="T1111111111111",
    )


def line(price):
    return [{"description": "x", "quantity": Decimal(1), "unit_price": Decimal(price), "tax_rate": "10"}]


def invoice(partner, price, date=JUNE_1):
    return issue_document(
        save_document(Invoice(partner=partner, issue_date=date), line(price)),
        "pdf/invoice.html",
        on_issue=post_invoice,
    )


def bill(partner, price, date=JUNE_1):
    return issue_document(
        save_document(Bill(partner=partner, issue_date=date), line(price)),
        "pdf/bill.html",
        on_issue=post_bill,
    )


def balances(journal):
    return {(ln.account.name, ln.side): ln.amount for ln in journal.lines.select_related("account")}


def test_apply_advance_received(customer, fiscal_years):
    receipt = create_receipt(
        partner=customer,
        date=D(2026, 5, 1),
        deposit_account=Account.by_key("bank"),
        deposit_sub_account=None,
        amount=Decimal(50000),
        fee=Decimal(0),
        memo="着手金",
        allocations=[],
        user=None,
    )
    assert receipt.advance_amount == 50000
    inv = invoice(customer, 30000)  # 33,000
    with pytest.raises(ValidationError, match="未決済額"):
        apply_advance(SALES, receipt, inv, Decimal(40000), D(2026, 6, 5))
    with pytest.raises(ValidationError, match="入出金日以降"):
        apply_advance(SALES, receipt, inv, Decimal(1000), D(2026, 4, 30))
    alloc = apply_advance(SALES, receipt, inv, Decimal(33000), D(2026, 6, 5))
    assert inv.payment_status == "入金済" and inv.outstanding == 0
    receipt.refresh_from_db()
    assert receipt.advance_amount == 17000
    assert balances(alloc.applied_journal) == {("前受金", "D"): 33000, ("売掛金", "C"): 33000}
    assert all(ln.partner_id == customer.pk for ln in alloc.applied_journal.lines.all())
    inv2 = invoice(customer, 20000)  # 22,000 > 残額17,000
    with pytest.raises(ValidationError, match="残額（17,000円）"):
        apply_advance(SALES, receipt, inv2, Decimal(22000), D(2026, 6, 5))

    # 充当がある間は入金も請求書も取り消せない
    with pytest.raises(ValidationError, match="充当を取り消して"):
        cancel_receipt(receipt, "x", None)
    with pytest.raises(ValidationError, match="入金消込済み"):
        cancel_document(inv, "x", on_cancel=cancel_invoice)
    cancel_application(SALES, alloc, "誤り")
    alloc.refresh_from_db()
    assert alloc.cancelled_at and alloc.applied_journal.is_reversed
    assert inv.outstanding == 33000
    receipt.refresh_from_db()
    assert receipt.advance_amount == 50000
    with pytest.raises(ValidationError, match="すでに取り消されて"):
        cancel_application(SALES, alloc, "again")
    cancel_document(inv, "訂正", on_cancel=cancel_invoice)
    cancel_receipt(receipt, "返金", None)


def test_receipt_time_allocation_cannot_be_cancelled_as_application(customer, fiscal_years):
    inv = invoice(customer, 10000)
    receipt = create_receipt(
        partner=customer,
        date=D(2026, 6, 10),
        deposit_account=Account.by_key("bank"),
        deposit_sub_account=None,
        amount=Decimal(11000),
        fee=Decimal(0),
        memo="",
        allocations=[(inv, Decimal(11000))],
        user=None,
    )
    with pytest.raises(ValidationError, match="入出金そのもの"):
        cancel_application(SALES, receipt.allocations.get(), "x")


def test_apply_advance_paid(supplier, fiscal_years):
    payment = create_payment(
        partner=supplier,
        date=D(2026, 5, 1),
        pay_account=Account.by_key("bank"),
        pay_sub_account=None,
        amount=Decimal(100000),
        fee=Decimal(0),
        deduction=Decimal(0),
        memo="前払",
        allocations=[],
        user=None,
    )
    b = bill(supplier, 50000)  # 55,000
    alloc = apply_advance(PURCHASE, payment, b, Decimal(30000), D(2026, 6, 2))
    assert b.payment_status == "一部支払" and b.outstanding == 25000
    assert balances(alloc.applied_journal) == {("買掛金", "D"): 30000, ("前渡金", "C"): 30000}
    with pytest.raises(ValidationError, match="充当を取り消して"):
        cancel_payment(payment, "x", None)
    other = Partner.objects.create(code="S2", name="別会社", is_customer=False, is_supplier=True)
    with pytest.raises(ValidationError, match="取引先が異なります"):
        apply_advance(PURCHASE, payment, bill(other, 1000), Decimal(100), D(2026, 6, 2))


def test_advance_views(admin_client, customer, supplier, fiscal_years):
    receipt = create_receipt(
        partner=customer,
        date=D(2026, 5, 1),
        deposit_account=Account.by_key("bank"),
        deposit_sub_account=None,
        amount=Decimal(50000),
        fee=Decimal(0),
        memo="",
        allocations=[],
        user=None,
    )
    inv = invoice(customer, 30000)
    page = admin_client.get(f"/sales/invoices/{inv.pk}/").content.decode()
    assert "前受金を充当する" in page and receipt.number in page
    resp = admin_client.post(
        f"/sales/invoices/{inv.pk}/apply-advance/",
        {"source": receipt.pk, "amount": "33000", "date": "2026-06-05"},
    )
    assert resp.status_code == 302
    assert inv.payment_status == "入金済"
    page = admin_client.get(f"/sales/invoices/{inv.pk}/").content.decode()
    assert "前受金充当" in page and "前受金を充当する" not in page
    alloc = receipt.allocations.get()
    admin_client.post(f"/sales/advance-applications/{alloc.pk}/cancel/", {"reason": "テスト"})
    alloc.refresh_from_db()
    assert alloc.cancelled_at
    for url in ["/sales/advances/", "/purchasing/advances/", f"/sales/receipts/{receipt.pk}/"]:
        assert admin_client.get(url).status_code == 200, url
    assert "17,000" not in admin_client.get("/sales/advances/").content.decode()
    assert "50,000" in admin_client.get("/sales/advances/").content.decode()


def test_viewer_cannot_apply(client, make_user, customer, fiscal_years):
    client.force_login(make_user("viewer", "viewer"))
    inv = invoice(customer, 1000)
    assert client.post(f"/sales/invoices/{inv.pk}/apply-advance/", {}).status_code == 403
