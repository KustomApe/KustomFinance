import datetime
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.banking.models import BankAccount, BankRule, BankTransaction, ImportProfile
from apps.banking.parsing import normalize_name, parse_amount, parse_date
from apps.banking.services import (
    apply_match,
    candidates,
    ignore_transaction,
    import_statement,
    match_rule,
    post_transaction,
    reconciliation,
    reopen_transaction,
)
from apps.ledger.models import Account, SubAccount, TaxCategory
from apps.masters.doc_services import issue_document, save_document
from apps.masters.models import Partner
from apps.purchasing.models import Bill
from apps.purchasing.services import post_bill
from apps.sales.models import Invoice
from apps.sales.services import post_invoice

D = datetime.date
pytestmark = pytest.mark.django_db

CSV = """日付,摘要,お引出し,お預入れ,残高
2026/10/1,振込 ｶ)ｻﾝﾌﾟﾙｼﾖｳｼﾞ,,"109,340","1,109,340"
R8.10.2,ﾃｽｳﾘﾖｳ,440,,"1,108,900"
2026-10-03,ﾃﾞﾝｷﾀﾞｲ ﾄｳｷﾖｳﾃﾞﾝﾘﾖｸ,"5,500",,"1,103,400"
2026年10月4日,振込 ﾌﾞﾋﾝｺｳｷﾞﾖｳ,"54,340",,"1,049,060"
2026/10/5,ﾃｽｳﾘﾖｳ,440,,"1,048,620"
""".encode("cp932")


@pytest.fixture(autouse=True)
def media(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def bank(db):
    sub = SubAccount.objects.create(account=Account.by_key("bank"), name="テスト銀行")
    return BankAccount.objects.create(
        name="テスト銀行 普通",
        account=Account.by_key("bank"),
        sub_account=sub,
        import_profile=ImportProfile.objects.get(name__startswith="汎用（日付・摘要・出金"),
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026/10/13", D(2026, 10, 13)),
        ("2026-1-5", D(2026, 1, 5)),
        ("20261013", D(2026, 10, 13)),
        ("R8.10.13", D(2026, 10, 13)),
        ("令和8年10月13日", D(2026, 10, 13)),
        ("２０２６／１０／１３", D(2026, 10, 13)),
    ],
)
def test_parse_date(text, expected):
    assert parse_date(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1,234", 1234),
        ("¥1,234", 1234),
        ("１，２３４円", 1234),
        ("", 0),
        ("-500", -500),
        ("△500", -500),
    ],
)
def test_parse_amount(text, expected):
    assert parse_amount(text) == expected


def test_normalize_name():
    assert normalize_name("ｶ)ｻﾝﾌﾟﾙｼﾖｳｼﾞ") == normalize_name("サンプルショウジ")
    assert normalize_name("株式会社サンプル商事") == "サンプル商事"


def test_import_and_dedupe(bank, make_user):
    user = make_user("u")
    batch, errors = import_statement(bank, "oct.csv", CSV, user)
    assert errors == [] and batch.imported == 5
    tx = BankTransaction.objects.order_by("id")[2]
    assert tx.withdrawal == 5500 and tx.balance == 1103400 and tx.date == D(2026, 10, 3)
    assert BankTransaction.objects.filter(withdrawal=440).count() == 2
    batch2, _ = import_statement(bank, "oct.csv", CSV, user)
    assert batch2.imported == 0 and batch2.skipped == 5


def test_match_invoice_and_bill(bank, make_user, fiscal_years):
    user = make_user("u")
    customer = Partner.objects.create(code="C1", name="株式会社サンプル商事", name_kana="サンプルショウジ")
    supplier = Partner.objects.create(
        code="S1",
        name="有限会社部品工業",
        name_kana="ブヒンコウギョウ",
        is_customer=False,
        is_supplier=True,
        invoice_registration_number="T1111111111111",
    )
    line = {"description": "x", "quantity": Decimal(1), "tax_rate": "10"}
    inv = issue_document(
        save_document(
            Invoice(partner=customer, issue_date=D(2026, 9, 30)), [{**line, "unit_price": Decimal(100000)}]
        ),
        "pdf/invoice.html",
        on_issue=post_invoice,
    )
    bill = issue_document(
        save_document(
            Bill(partner=supplier, issue_date=D(2026, 9, 30)), [{**line, "unit_price": Decimal(50000)}]
        ),
        "pdf/bill.html",
        on_issue=post_bill,
    )
    import_statement(bank, "oct.csv", CSV, user)
    deposit = BankTransaction.objects.get(deposit=109340)
    cands = candidates(deposit)
    assert cands and cands[0].document == inv and cands[0].fee == 660 and cands[0].name_match
    apply_match(deposit, inv, user)
    assert inv.payment_status == "入金済"
    deposit.refresh_from_db()
    assert deposit.status == "done" and deposit.journal

    withdrawal = BankTransaction.objects.get(withdrawal=54340)
    cands = candidates(withdrawal)
    assert cands[0].document == bill and cands[0].fee == 660
    apply_match(withdrawal, bill, user)
    assert bill.payment_status == "支払済"


def test_rules_ignore_and_reconciliation(bank, make_user, fiscal_years):
    user = make_user("u")
    BankRule.objects.create(
        keyword="ﾃｽｳﾘﾖｳ",
        direction="withdrawal",
        account=Account.by_key("fees"),
        tax_category=TaxCategory.objects.get(code="P10"),
        description="振込手数料",
    )
    BankRule.objects.create(
        keyword="トウキョウデンリョク",
        account=Account.objects.get(name="水道光熱費"),
        tax_category=TaxCategory.objects.get(code="P10"),
    )
    import_statement(bank, "oct.csv", CSV, user)
    fee = BankTransaction.objects.filter(withdrawal=440).first()
    rule = match_rule(fee)
    assert rule.account.name == "支払手数料"
    post_transaction(
        fee, user, account=rule.account, tax_category=rule.tax_category, description=rule.description
    )
    fee.refresh_from_db()
    lines = {ln.account.name: ln.amount for ln in fee.journal.lines.select_related("account")}
    assert lines == {"支払手数料": 400, "仮払消費税": 40, "普通預金": 440}
    elec = BankTransaction.objects.get(withdrawal=5500)
    assert match_rule(elec).account.name == "水道光熱費"
    other = BankTransaction.objects.filter(withdrawal=440, status="unprocessed").get()
    ignore_transaction(other, "テスト")
    reopen_transaction(other)
    other.refresh_from_db()
    assert other.status == "unprocessed"
    r = reconciliation(bank, D(2026, 10, 31))
    assert r["statement_balance"] == 1048620 and r["book_balance"] == -440 and r["unprocessed"] == 4


def test_banking_views(admin_client, bank, fiscal_years):
    resp = admin_client.post(
        "/banking/import/", {"bank_account": bank.pk, "file": SimpleUploadedFile("a.csv", CSV)}
    )
    assert resp.status_code == 302
    assert BankTransaction.objects.count() == 5
    assert admin_client.get("/banking/transactions/").status_code == 200
    tx = BankTransaction.objects.get(withdrawal=5500)
    assert admin_client.get(f"/banking/transactions/{tx.pk}/form/").status_code == 200
    resp = admin_client.post(
        f"/banking/transactions/{tx.pk}/action/",
        {
            "action": "post",
            "account": Account.objects.get(name="水道光熱費").pk,
            "tax_category": TaxCategory.objects.get(code="P10").pk,
        },
        HTTP_HX_REQUEST="true",
    )
    assert resp.status_code == 200 and "処理済" in resp.content.decode()
    resp = admin_client.post(
        f"/banking/transactions/{tx.pk}/action/", {"action": "ignore"}, HTTP_HX_REQUEST="true"
    )
    assert "すでに処理されています" in resp.content.decode()
    for url in [
        "/banking/reconciliation/",
        "/banking/accounts/",
        "/banking/rules/",
        "/banking/profiles/",
        "/banking/rules/new/",
        f"/banking/accounts/{bank.pk}/",
        "/banking/import/",
    ]:
        assert admin_client.get(url).status_code == 200, url
