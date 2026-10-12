import pytest

from apps.accounts.roles import Role


@pytest.fixture
def make_user(db, django_user_model):
    def _make(username="user", role=Role.ADMIN, **kwargs):
        return django_user_model.objects.create_user(
            username=username, password="pass-12345!", role=role, **kwargs
        )

    return _make


@pytest.fixture
def admin_client(client, make_user):
    client.force_login(make_user("admin", Role.ADMIN))
    return client


@pytest.fixture
def fiscal_years(db):
    import datetime

    from apps.core.models import Company, FiscalYear

    company = Company.load()
    company.fiscal_year_start_month = 4
    company.save()
    return [
        FiscalYear.objects.create(
            name="第1期", start_date=datetime.date(2025, 4, 1), end_date=datetime.date(2026, 3, 31)
        ),
        FiscalYear.objects.create(
            name="第2期", start_date=datetime.date(2026, 4, 1), end_date=datetime.date(2027, 3, 31)
        ),
    ]
