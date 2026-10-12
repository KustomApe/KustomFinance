import datetime

from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models

from apps.audit.models import AuditedModel

from .money import Rounding

invoice_registration_validator = RegexValidator(
    r"^T\d{13}$", "適格請求書発行事業者登録番号は「T」+13桁の数字で入力してください。"
)


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField("作成日時", auto_now_add=True)
    updated_at = models.DateTimeField("更新日時", auto_now=True)

    class Meta:
        abstract = True


class Company(AuditedModel, TimeStampedModel):
    """自社情報（1レコードのみ）。"""

    name = models.CharField("会社名", max_length=200, default="自社名を設定してください")
    representative = models.CharField("代表者", max_length=100, blank=True)
    postal_code = models.CharField("郵便番号", max_length=10, blank=True)
    address = models.CharField("住所", max_length=255, blank=True)
    phone = models.CharField("電話番号", max_length=30, blank=True)
    fax = models.CharField("FAX", max_length=30, blank=True)
    email = models.EmailField("メール", blank=True)
    corporate_number = models.CharField(
        "法人番号",
        max_length=13,
        blank=True,
        validators=[RegexValidator(r"^\d{13}$", "法人番号は13桁の数字です。")],
    )
    invoice_registration_number = models.CharField(
        "適格請求書発行事業者登録番号",
        max_length=14,
        blank=True,
        validators=[invoice_registration_validator],
    )
    fiscal_year_start_month = models.PositiveSmallIntegerField(
        "期首月", default=4, validators=[MinValueValidator(1), MaxValueValidator(12)]
    )
    tax_rounding = models.CharField(
        "消費税の端数処理",
        max_length=10,
        choices=Rounding.choices,
        default=Rounding.FLOOR,
        help_text="請求書ごと・税率ごとに1回適用します（インボイス制度の要件）。",
    )
    bank_account_info = models.TextField(
        "振込先（請求書に印字）", blank=True, help_text="例: ○○銀行 △△支店 普通 1234567 カ）ジシャ"
    )
    seal_image = models.ImageField("角印画像", upload_to="company/", blank=True)
    books_locked_through = models.DateField(
        "月次締め日", null=True, blank=True, help_text="この日以前の日付では仕訳を登録できません。"
    )

    class Meta:
        verbose_name = "自社情報"
        verbose_name_plural = "自社情報"

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "Company":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def fiscal_year_of(self, date: datetime.date) -> int:
        """日付が属する事業年度を、期首の年で返す。"""
        return date.year if date.month >= self.fiscal_year_start_month else date.year - 1


class FiscalYear(AuditedModel, TimeStampedModel):
    name = models.CharField("名称", max_length=50, help_text="例: 第5期")
    start_date = models.DateField("期首日", unique=True)
    end_date = models.DateField("期末日")
    is_closed = models.BooleanField("決算締め済み", default=False)

    class Meta:
        verbose_name = "会計期間"
        verbose_name_plural = "会計期間"
        ordering = ["-start_date"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__gt=models.F("start_date")), name="fiscal_year_end_after_start"
            )
        ]

    def __str__(self) -> str:
        return f"{self.name}（{self.start_date:%Y/%m/%d}〜{self.end_date:%Y/%m/%d}）"

    @classmethod
    def for_date(cls, date: datetime.date) -> "FiscalYear | None":
        return cls.objects.filter(start_date__lte=date, end_date__gte=date).first()


class NumberSequence(models.Model):
    """帳票番号の採番。年度ごとに欠番なく連番を発行する。"""

    key = models.CharField("種別", max_length=30)
    year = models.PositiveIntegerField("年度")
    last_number = models.PositiveIntegerField("最終番号", default=0)

    class Meta:
        verbose_name = "採番"
        verbose_name_plural = "採番"
        constraints = [models.UniqueConstraint(fields=["key", "year"], name="unique_sequence_key_year")]

    def __str__(self) -> str:
        return f"{self.key} {self.year}: {self.last_number}"
