import datetime
from decimal import Decimal

import pytest
from django.db import connection

from apps.audit.models import Action, AuditLog
from apps.core.models import Company
from apps.core.money import Rounding, round_yen
from apps.core.numbering import next_number


@pytest.mark.parametrize(
    ("value", "method", "expected"),
    [
        ("123.9", Rounding.FLOOR, 123),
        ("123.5", Rounding.HALF_UP, 124),
        ("123.4", Rounding.HALF_UP, 123),
        ("123.1", Rounding.CEIL, 124),
        ("-123.9", Rounding.FLOOR, -123),
        ("-123.1", Rounding.CEIL, -124),
    ],
)
def test_round_yen(value, method, expected):
    assert round_yen(Decimal(value), method) == expected


@pytest.mark.django_db
def test_next_number_by_fiscal_year():
    company = Company.load()
    company.fiscal_year_start_month = 4
    company.save()
    assert next_number("invoice", datetime.date(2026, 3, 31)) == "INV-2025-00001"
    assert next_number("invoice", datetime.date(2026, 4, 1)) == "INV-2026-00001"
    assert next_number("invoice", datetime.date(2026, 5, 1)) == "INV-2026-00002"
    assert next_number("estimate", datetime.date(2026, 5, 1)) == "EST-2026-00001"


@pytest.mark.django_db
def test_audited_model_records_changes(make_user):
    company = Company.load()
    company.name = "株式会社テスト"
    company.save()
    log = AuditLog.objects.filter(action=Action.UPDATE).first()
    assert log.changes["name"] == ["自社名を設定してください", "株式会社テスト"]


@pytest.mark.django_db
def test_audit_log_is_immutable():
    Company.load()
    log = AuditLog.objects.first()
    with pytest.raises(Exception, match="操作ログは変更・削除できません"):
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM audit_auditlog WHERE id = %s", [log.id])


@pytest.mark.django_db
def test_company_invoice_number_validation(admin_client):
    resp = admin_client.post(
        "/settings/company/",
        {
            "name": "株式会社テスト",
            "fiscal_year_start_month": 4,
            "tax_rounding": "floor",
            "invoice_registration_number": "1234",
        },
    )
    assert resp.status_code == 200
    assert "登録番号は「T」+13桁" in resp.content.decode()
