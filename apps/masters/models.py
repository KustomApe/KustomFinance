import calendar
import datetime

from django.db import models

from apps.audit.models import AuditedModel
from apps.core.models import TimeStampedModel, invoice_registration_validator


class Partner(AuditedModel, TimeStampedModel):
    """取引先（得意先・仕入先）。"""

    class Honorific(models.TextChoices):
        ONCHU = "御中", "御中"
        SAMA = "様", "様"

    code = models.CharField("コード", max_length=20, unique=True)
    name = models.CharField("取引先名", max_length=200)
    name_kana = models.CharField("フリガナ", max_length=200, blank=True)
    honorific = models.CharField("敬称", max_length=4, choices=Honorific.choices, default=Honorific.ONCHU)
    is_customer = models.BooleanField("得意先", default=True)
    is_supplier = models.BooleanField("仕入先", default=False)
    invoice_registration_number = models.CharField(
        "適格請求書発行事業者登録番号",
        max_length=14,
        blank=True,
        validators=[invoice_registration_validator],
        help_text="仕入先が適格請求書発行事業者でない場合は空欄（仕入税額控除は経過措置の割合になります）。",
    )
    postal_code = models.CharField("郵便番号", max_length=10, blank=True)
    address = models.CharField("住所", max_length=255, blank=True)
    phone = models.CharField("電話番号", max_length=30, blank=True)
    email = models.EmailField("メール", blank=True)
    contact_person = models.CharField("担当者", max_length=100, blank=True)
    closing_day = models.PositiveSmallIntegerField(
        "締日", default=0, help_text="0 = 月末締め、1〜28 = 毎月その日に締め"
    )
    payment_month_offset = models.PositiveSmallIntegerField(
        "支払月", default=1, help_text="0 = 当月、1 = 翌月、2 = 翌々月"
    )
    payment_day = models.PositiveSmallIntegerField("支払日", default=0, help_text="0 = 月末、1〜28 = その日")
    bank_account_info = models.TextField("振込先口座（仕入先）", blank=True)
    notes = models.TextField("備考", blank=True)
    is_active = models.BooleanField("有効", default=True)

    class Meta:
        verbose_name = "取引先"
        verbose_name_plural = "取引先"
        ordering = ["code"]

    def __str__(self) -> str:
        return self.name

    @property
    def display_name(self) -> str:
        return f"{self.name} {self.honorific}"

    @property
    def is_qualified_issuer(self) -> bool:
        return bool(self.invoice_registration_number)

    def due_date_for(self, date: datetime.date) -> datetime.date:
        """取引日から、締日・支払条件に基づく支払期日を求める。"""
        year, month = date.year, date.month
        if self.closing_day and date.day > self.closing_day:
            month += 1  # 締日を過ぎた取引は翌月締め
        month += self.payment_month_offset
        year += (month - 1) // 12
        month = (month - 1) % 12 + 1
        last = calendar.monthrange(year, month)[1]
        return datetime.date(year, month, min(self.payment_day or last, last))


class TaxRate(models.TextChoices):
    """帳票明細の税率。記帳時に販売・購買それぞれの税区分へ変換する。"""

    STANDARD = "10", "10%"
    REDUCED = "8R", "8%（軽減）"
    EXEMPT = "exempt", "非課税"
    EXPORT = "export", "免税（輸出）"
    NONE = "none", "対象外"


TAX_RATE_PERCENT = {TaxRate.STANDARD: 10, TaxRate.REDUCED: 8}


class Item(AuditedModel, TimeStampedModel):
    code = models.CharField("コード", max_length=30, unique=True)
    name = models.CharField("品名", max_length=200)
    unit = models.CharField("単位", max_length=10, blank=True, default="式")
    unit_price = models.DecimalField("販売単価", max_digits=15, decimal_places=2, default=0)
    purchase_price = models.DecimalField("仕入単価", max_digits=15, decimal_places=2, default=0)
    tax_rate = models.CharField("税率", max_length=10, choices=TaxRate.choices, default=TaxRate.STANDARD)
    sales_account = models.ForeignKey(
        "ledger.Account",
        verbose_name="売上科目",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        help_text="空欄なら「売上高」",
    )
    purchase_account = models.ForeignKey(
        "ledger.Account",
        verbose_name="仕入科目",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        help_text="空欄なら「仕入高」",
    )
    is_active = models.BooleanField("有効", default=True)

    class Meta:
        verbose_name = "品目"
        verbose_name_plural = "品目"
        ordering = ["code"]

    def __str__(self) -> str:
        return self.name


class Department(AuditedModel, TimeStampedModel):
    code = models.CharField("コード", max_length=20, unique=True)
    name = models.CharField("部門名", max_length=100)
    is_active = models.BooleanField("有効", default=True)

    class Meta:
        verbose_name = "部門"
        verbose_name_plural = "部門"
        ordering = ["code"]

    def __str__(self) -> str:
        return self.name


class Project(AuditedModel, TimeStampedModel):
    code = models.CharField("コード", max_length=20, unique=True)
    name = models.CharField("プロジェクト名", max_length=100)
    partner = models.ForeignKey(
        Partner, verbose_name="取引先", null=True, blank=True, on_delete=models.PROTECT
    )
    is_active = models.BooleanField("有効", default=True)

    class Meta:
        verbose_name = "プロジェクト"
        verbose_name_plural = "プロジェクト"
        ordering = ["code"]

    def __str__(self) -> str:
        return self.name
