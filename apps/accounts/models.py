from django.contrib.auth.models import AbstractUser
from django.db import models

from apps.audit.models import AuditedModel

from .roles import CAPABILITIES, Role


class User(AuditedModel, AbstractUser):
    audit_exclude = ("password", "last_login")

    display_name = models.CharField("表示名", max_length=100, blank=True)
    role = models.CharField("ロール", max_length=20, choices=Role.choices, default=Role.VIEWER)

    class Meta:
        verbose_name = "ユーザー"
        verbose_name_plural = "ユーザー"

    def __str__(self) -> str:
        return self.display_name or self.get_full_name() or self.username

    def can(self, capability: str) -> bool:
        if not self.is_active:
            return False
        if self.is_superuser:
            return True
        return capability in CAPABILITIES.get(self.role, set())
