import pytest

from apps.accounts.roles import Role


@pytest.mark.django_db
def test_login_required(client):
    resp = client.get("/")
    assert resp.status_code == 302
    assert resp.url.startswith("/accounts/login/")


@pytest.mark.django_db
def test_viewer_cannot_open_settings(client, make_user):
    client.force_login(make_user("viewer", Role.VIEWER))
    assert client.get("/").status_code == 200
    assert client.get("/settings/company/").status_code == 403
    assert client.get("/accounts/users/").status_code == 403


@pytest.mark.django_db
def test_admin_creates_user(admin_client, django_user_model):
    resp = admin_client.post(
        "/accounts/users/new/",
        {
            "username": "keiri",
            "display_name": "経理太郎",
            "role": Role.ACCOUNTANT,
            "is_active": "on",
            "password1": "Very-secret-123",
            "password2": "Very-secret-123",
        },
    )
    assert resp.status_code == 302
    user = django_user_model.objects.get(username="keiri")
    assert user.check_password("Very-secret-123")
    assert user.can("ledger_edit") and not user.can("settings")


@pytest.mark.django_db
def test_login_is_logged(client, make_user):
    from apps.audit.models import Action, AuditLog

    make_user("someone")
    client.post("/accounts/login/", {"username": "someone", "password": "pass-12345!"})
    assert AuditLog.objects.filter(action=Action.LOGIN).exists()
