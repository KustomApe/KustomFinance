from django.conf import settings
from django.db import models

from apps.audit.models import AuditedModel
from apps.core.files import file_sha256
from apps.core.models import TimeStampedModel
from apps.core.money import MoneyField


class Document(AuditedModel, TimeStampedModel):
    """電子取引データ・スキャンした証憑の保存。削除はできず、誤りは「無効」にして再登録する。"""

    class Kind(models.TextChoices):
        INVOICE_RECEIVED = "invoice_received", "請求書（受領）"
        INVOICE_ISSUED = "invoice_issued", "請求書（発行）"
        RECEIPT = "receipt", "領収書"
        ESTIMATE = "estimate", "見積書"
        ORDER = "order", "注文書・注文請書"
        DELIVERY = "delivery", "納品書"
        CONTRACT = "contract", "契約書"
        OTHER = "other", "その他"

    class Source(models.TextChoices):
        ELECTRONIC = "electronic", "電子取引"
        SCAN = "scan", "スキャン"
        OTHER = "other", "その他"

    kind = models.CharField("書類の種類", max_length=30, choices=Kind.choices)
    source = models.CharField("受領方法", max_length=20, choices=Source.choices, default=Source.ELECTRONIC)
    transaction_date = models.DateField("取引年月日", db_index=True)
    amount = MoneyField("取引金額", db_index=True)
    partner = models.ForeignKey(
        "masters.Partner",
        verbose_name="取引先",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    partner_name = models.CharField(
        "取引先名", max_length=200, blank=True, help_text="取引先マスタにない場合"
    )
    title = models.CharField("件名・内容", max_length=200)
    file = models.FileField("ファイル", upload_to="documents/%Y/%m/")
    file_sha256 = models.CharField("ファイルハッシュ(SHA-256)", max_length=64, editable=False)
    is_void = models.BooleanField("無効", default=False)
    void_reason = models.CharField("無効にした理由", max_length=200, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="登録者", null=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        verbose_name = "証憑"
        verbose_name_plural = "証憑"
        ordering = ["-transaction_date", "-id"]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} {self.transaction_date} {self.display_partner} {self.amount}"

    @property
    def display_partner(self) -> str:
        return self.partner.name if self.partner else self.partner_name

    def save(self, *args, **kwargs):
        if self.pk:
            original = type(self).objects.only("file").get(pk=self.pk)
            if original.file.name != self.file.name:
                raise ValueError("保存済みのファイルは差し替えできません。無効にして再登録してください。")
        elif self.file:
            self.file_sha256 = file_sha256(self.file)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("証憑は削除できません。無効にしてください。")
