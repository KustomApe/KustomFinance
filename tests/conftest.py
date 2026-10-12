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
