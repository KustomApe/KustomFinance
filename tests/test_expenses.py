import datetime

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.roles import Role
from apps.expenses import services
from apps.expenses.models import ExpenseClaim, ExpenseLine
from apps.ledger.models import Account, TaxCategory

D = datetime.date
pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def media(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path


def make_claim(user, *lines):
    claim = ExpenseClaim.objects.create(applicant=user, title="10月出張")
    for kw in lines:
        ExpenseLine.objects.create(
            claim=claim,
            **{
                "date": D(2026, 10, 5),
                "account": Account.objects.get(name="旅費交通費"),
                "tax_category": TaxCategory.objects.get(code="P10"),
                "payee": "JR",
                "description": "新幹線",
                **kw,
            },
        )
    claim.recalculate()
    claim.save()
    return claim


def test_effective_tax_category(make_user):
    user = make_user("u")
    claim = make_claim(user, {"amount": 11000})
    line = claim.lines.get()
    assert services.effective_tax_category(line).code == "P10-50"
    line.invoice_exempt = True
    assert services.effective_tax_category(line).code == "P10"
    line.invoice_exempt, line.payee_registration_number = False, "T1234567890123"
    assert services.effective_tax_category(line).code == "P10"


def test_claim_workflow(make_user, fiscal_years):
    applicant, approver = make_user("staff", Role.SALES), make_user("keiri", Role.ACCOUNTANT)
    claim = make_claim(
        applicant,
        {"amount": 14520, "invoice_exempt": True},
        {"amount": 3300, "account": Account.objects.get(name="会議費"), "payee": "喫茶店"},
    )
    assert claim.total == 17820
    with pytest.raises(ValidationError, match="本人のみ"):
        services.submit(claim, approver)
    claim = services.submit(claim, applicant)
    assert claim.number == "EXP-2026-00001" and claim.status == "submitted"
    with pytest.raises(ValidationError, match="自分の申請"):
        services.approve(claim, applicant, D(2026, 10, 10))
    claim = services.reject(claim, approver, "領収書を添付してください")
    assert claim.is_editable
    claim = services.submit(claim, applicant)
    claim = services.approve(claim, approver, D(2026, 10, 10))
    lines = {}
    for ln in claim.journal.lines.select_related("account"):
        lines[(ln.account.name, ln.side)] = lines.get((ln.account.name, ln.side), 0) + ln.amount
    # 特例の交通費は全額控除 1,320、登録番号なしの会議費は経過措置50% → 300*0.5=150
    assert lines[("旅費交通費", "D")] == 13200
    assert lines[("会議費", "D")] == 3150
    assert lines[("仮払消費税", "D")] == 1320 + 150
    assert lines[("未払金", "C")] == 17820
    claim = services.pay(claim, approver, D(2026, 10, 25), Account.by_key("bank"))
    assert claim.status == "paid" and claim.payment_journal
    with pytest.raises(ValidationError):
        services.cancel(claim, approver, "x")


def test_cancel_approved_claim(make_user, fiscal_years):
    applicant, approver = make_user("staff", Role.SALES), make_user("keiri", Role.ACCOUNTANT)
    claim = services.submit(make_claim(applicant, {"amount": 1000}), applicant)
    claim = services.approve(claim, approver, D(2026, 10, 10))
    claim = services.cancel(claim, approver, "重複申請")
    assert claim.status == "cancelled" and claim.journal.is_reversed


def test_claim_views(client, make_user, fiscal_years):
    staff = make_user("staff", Role.SALES)
    client.force_login(staff)
    data = {
        "title": "備品購入",
        "lines-TOTAL_FORMS": "3",
        "lines-INITIAL_FORMS": "0",
        "lines-MIN_NUM_FORMS": "0",
        "lines-MAX_NUM_FORMS": "1000",
        "lines-0-date": "2026-10-03",
        "lines-0-account": Account.objects.get(name="消耗品費").pk,
        "lines-0-tax_category": TaxCategory.objects.get(code="P10").pk,
        "lines-0-amount": "2200",
        "lines-0-payee": "文具店",
        "lines-0-description": "ノート",
        "lines-0-payee_registration_number": "T1234567890123",
        "lines-0-receipt": SimpleUploadedFile("r.jpg", b"jpegdata"),
        "submit": "1",
    }
    resp = client.post("/expenses/new/", data)
    assert resp.status_code == 302, [f.errors for f in resp.context["formset"]] + [
        resp.context["form"].errors
    ]
    claim = ExpenseClaim.objects.get()
    assert claim.status == "submitted" and claim.total == 2200
    line = claim.lines.get()
    assert len(line.receipt_sha256) == 64
    assert client.get(f"/expenses/receipts/{line.pk}/").status_code == 200
    # 他人の申請は見られない
    other = make_user("other", Role.SALES)
    client.force_login(other)
    assert client.get(f"/expenses/{claim.pk}/").status_code == 403
    # 経理が承認
    client.force_login(make_user("keiri", Role.ACCOUNTANT))
    assert client.get("/expenses/?tab=approval").status_code == 200
    resp = client.post(f"/expenses/{claim.pk}/", {"action": "approve", "posting_date": "2026-10-10"})
    claim.refresh_from_db()
    assert claim.status == "approved"
    client.post(
        f"/expenses/{claim.pk}/",
        {"action": "pay", "date": "2026-10-25", "account": Account.by_key("bank").pk},
    )
    claim.refresh_from_db()
    assert claim.status == "paid"
