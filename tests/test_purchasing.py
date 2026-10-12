import datetime
import hashlib
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.ledger.models import Account
from apps.masters.doc_services import cancel_document, issue_document, save_document
from apps.masters.documents import DocStatus
from apps.masters.models import Partner
from apps.purchasing.models import Bill, GoodsReceipt, PurchaseOrder
from apps.purchasing.services import (
    bill_from_receipts,
    cancel_bill,
    cancel_payment,
    create_payment,
    post_bill,
    purchase_tax_code,
)

D = datetime.date
pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def media(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def supplier(db):
    return Partner.objects.create(
        code="S001",
        name="株式会社仕入先",
        is_customer=False,
        is_supplier=True,
        invoice_registration_number="T1111111111111",
        closing_day=0,
        payment_month_offset=1,
        payment_day=0,
    )


@pytest.fixture
def small_supplier(db):
    return Partner.objects.create(code="S002", name="個人事業主", is_customer=False, is_supplier=True)


def line(desc, qty, price, rate="10"):
    return {"description": desc, "quantity": Decimal(qty), "unit_price": Decimal(price), "tax_rate": rate}


def make_bill(partner, lines, issue_date=None, **kw):
    return save_document(Bill(partner=partner, issue_date=issue_date or D(2026, 10, 15), **kw), lines)


def issue_bill(bill):
    return issue_document(bill, "pdf/bill.html", on_issue=post_bill)


def balances(journal):
    out = {}
    for ln in journal.lines.select_related("account"):
        key = (ln.account.name, ln.side)
        out[key] = out.get(key, 0) + ln.amount
    return out


@pytest.mark.parametrize(
    ("rate", "qualified", "date", "expected"),
    [
        ("10", True, D(2026, 10, 1), "P10"),
        ("8R", True, D(2026, 10, 1), "P8R"),
        ("10", False, D(2026, 9, 30), "P10-80"),
        ("10", False, D(2026, 10, 1), "P10-50"),
        ("8R", False, D(2029, 9, 30), "P8R-50"),
        ("10", False, D(2029, 10, 1), "P10-0"),
        ("exempt", False, D(2026, 10, 1), "PNT"),
        ("none", True, D(2026, 10, 1), "OUT"),
    ],
)
def test_purchase_tax_code(rate, qualified, date, expected):
    assert purchase_tax_code(rate, qualified, date) == expected


def test_qualified_bill(supplier, fiscal_years):
    bill = issue_bill(make_bill(supplier, [line("部品", 100, 1000)], supplier_invoice_number="A-123"))
    assert bill.number == "BILL-2026-00001"
    assert bill.supplier_registration_number == "T1111111111111"
    assert bill.due_date == D(2026, 11, 30)
    b = balances(bill.journal)
    assert b[("仕入高", "D")] == 100000 and b[("仮払消費税", "D")] == 10000 and b[("買掛金", "C")] == 110000
    assert bill.journal.lines.filter(partner=supplier).count() == 3


@pytest.mark.parametrize(
    ("date", "deductible"), [(D(2026, 9, 30), 8000), (D(2026, 10, 1), 5000), (D(2029, 10, 1), 0)]
)
def test_non_qualified_bill_transitional(small_supplier, fiscal_years, date, deductible):
    from apps.core.models import FiscalYear

    FiscalYear.objects.get_or_create(
        start_date=D(2029, 4, 1), defaults={"name": "第5期", "end_date": D(2030, 3, 31)}
    )
    bill = issue_bill(make_bill(small_supplier, [line("作業", 1, 100000)], issue_date=date))
    b = balances(bill.journal)
    assert b.get(("仮払消費税", "D"), 0) == deductible
    assert b[("仕入高", "D")] == 110000 - deductible
    assert b[("買掛金", "C")] == 110000


def test_tax_override_and_expense_account(supplier, fiscal_years):
    outsourcing = Account.objects.get(name="外注費")
    bill = make_bill(
        supplier,
        [line("A", 3, 33.3), line("B", 1, 99999)],
        account=outsourcing,
        tax_10_override=Decimal(10009),
    )
    assert bill.tax_total == 10009 and bill.total == 99 + 99999 + 10009
    bill = issue_bill(bill)
    b = balances(bill.journal)
    assert b[("仮払消費税", "D")] == 10009 and b[("外注費", "D")] == 100098


def test_attachment_hash(supplier, fiscal_years):
    bill = make_bill(supplier, [line("A", 1, 1000)])
    bill.attachment = SimpleUploadedFile("invoice.pdf", b"%PDF-1.4 test")
    bill.save()
    assert bill.attachment_sha256 == hashlib.sha256(b"%PDF-1.4 test").hexdigest()


def test_payment_with_fees(supplier, fiscal_years):
    bill = issue_bill(make_bill(supplier, [line("部品", 1, 100000)]))
    bank = Account.by_key("bank")
    # 先方負担の手数料660円を差し引いて109,340円を振込、当社負担の振込手数料440円
    p = create_payment(
        partner=supplier,
        date=D(2026, 11, 30),
        pay_account=bank,
        pay_sub_account=None,
        amount=Decimal(109340),
        fee=Decimal(440),
        deduction=Decimal(660),
        memo="",
        user=None,
        allocations=[(bill, Decimal(110000))],
    )
    assert bill.payment_status == "支払済"
    b = balances(p.journal)
    assert b[("買掛金", "D")] == 110000
    assert b[("普通預金", "C")] == 109780
    assert b[("支払手数料", "D")] == 400 and b[("支払手数料", "C")] == 600
    with pytest.raises(ValidationError, match="支払消込済み"):
        cancel_document(bill, "x", on_cancel=cancel_bill)
    cancel_payment(p, "誤り", None)
    assert bill.outstanding == 110000
    cancel_document(bill, "誤り", on_cancel=cancel_bill)
    bill.refresh_from_db()
    assert bill.status == DocStatus.CANCELLED and bill.journal.is_reversed


def test_bill_from_receipts(supplier, fiscal_years):
    r1 = issue_document(
        save_document(GoodsReceipt(partner=supplier, issue_date=D(2026, 10, 2)), [line("A", 1, 1000)]),
        "pdf/goods_receipt.html",
    )
    r2 = issue_document(
        save_document(GoodsReceipt(partner=supplier, issue_date=D(2026, 10, 9)), [line("B", 1, 2000)]),
        "pdf/goods_receipt.html",
    )
    bill = bill_from_receipts([r1, r2], None, D(2026, 10, 31))
    assert bill.subtotal == 3000 and bill.lines.count() == 2
    r1.refresh_from_db()
    assert r1.bill == bill


def test_purchasing_flow_via_views(admin_client, supplier, fiscal_years):
    data = {
        "partner": supplier.pk,
        "issue_date": "2026-10-01",
        "subject": "部品発注",
        "lines-TOTAL_FORMS": "1",
        "lines-INITIAL_FORMS": "0",
        "lines-MIN_NUM_FORMS": "0",
        "lines-MAX_NUM_FORMS": "300",
        "lines-0-description": "部品A",
        "lines-0-quantity": "10",
        "lines-0-unit_price": "5000",
        "lines-0-tax_rate": "10",
    }
    assert admin_client.post("/purchasing/orders/new/", data).status_code == 302
    po = PurchaseOrder.objects.get()
    admin_client.post(f"/purchasing/orders/{po.pk}/issue/")
    assert admin_client.get(f"/purchasing/orders/{po.pk}/pdf/").status_code == 200
    admin_client.post(f"/purchasing/orders/{po.pk}/to-bill/")
    bill = po.bills.get()
    edit = {
        **data,
        "supplier_invoice_number": "INV-999",
        "issue_date": "2026-10-20",
        "attachment": SimpleUploadedFile("received.pdf", b"%PDF-1.4 x"),
    }
    resp = admin_client.post(f"/purchasing/bills/{bill.pk}/edit/", edit)
    assert resp.status_code == 302, resp.content.decode()[:2000]
    admin_client.post(f"/purchasing/bills/{bill.pk}/issue/")
    bill.refresh_from_db()
    assert bill.status == DocStatus.ISSUED and bill.attachment_sha256
    assert admin_client.get(f"/purchasing/bills/{bill.pk}/attachment/").status_code == 200
    resp = admin_client.post(
        f"/purchasing/payments/new/?partner={supplier.pk}",
        {
            "partner": supplier.pk,
            "date": "2026-11-30",
            "pay_account": Account.by_key("bank").pk,
            "amount": "55000",
            "fee": "0",
            "deduction": "0",
            f"alloc-{bill.pk}": "55000",
        },
    )
    assert resp.status_code == 302, resp.content.decode()[:3000]
    assert bill.payment_status == "支払済"
    for url in [
        "/purchasing/orders/",
        "/purchasing/receipts/",
        "/purchasing/bills/",
        "/purchasing/unbilled/",
        "/purchasing/payments/",
        "/purchasing/payables/",
        "/purchasing/payables/?format=csv",
        "/purchasing/schedule/",
        "/purchasing/schedule/?format=csv",
        f"/purchasing/bills/{bill.pk}/",
        "/purchasing/receipts/new/",
        "/sales/receivables/",
    ]:
        assert admin_client.get(url).status_code == 200, url
