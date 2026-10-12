from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models


class Action(models.TextChoices):
    CREATE = "create", "作成"
    UPDATE = "update", "更新"
    DELETE = "delete", "削除"
    CONFIRM = "confirm", "確定"
    CANCEL = "cancel", "取消"
    LOGIN = "login", "ログイン"
    OTHER = "other", "その他"


class AuditLog(models.Model):
    """操作ログ（訂正削除履歴）。DBトリガーにより更新・削除不可。"""

    timestamp = models.DateTimeField("日時", auto_now_add=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="ユーザー",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    action = models.CharField("操作", max_length=20, choices=Action.choices)
    content_type = models.ForeignKey(
        ContentType, verbose_name="対象種別", null=True, blank=True, on_delete=models.PROTECT
    )
    object_id = models.CharField("対象ID", max_length=64, blank=True, db_index=True)
    object_repr = models.CharField("対象", max_length=255, blank=True)
    changes = models.JSONField("変更内容", default=dict, encoder=DjangoJSONEncoder)
    note = models.TextField("備考", blank=True)
    ip_address = models.GenericIPAddressField("IPアドレス", null=True, blank=True)

    class Meta:
        verbose_name = "操作ログ"
        verbose_name_plural = "操作ログ"
        ordering = ["-timestamp", "-id"]
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self) -> str:
        return f"{self.timestamp:%Y-%m-%d %H:%M} {self.get_action_display()} {self.object_repr}"

    def change_rows(self) -> list[tuple[str, object, object]]:
        """変更内容を (項目名, 変更前, 変更後) の一覧で返す。項目名はモデルの verbose_name。"""
        model = self.content_type.model_class() if self.content_type else None
        labels = {}
        if model:
            for field in model._meta.concrete_fields:
                labels[field.name] = labels[field.attname] = str(field.verbose_name)
        return [(labels.get(key, key), old, new) for key, (old, new) in self.changes.items()]


class AuditedModel(models.Model):
    """継承したモデルの作成・更新・削除を自動で AuditLog に記録する。"""

    audit_exclude: tuple[str, ...] = ("updated_at",)

    class Meta:
        abstract = True
