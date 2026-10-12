"""販売・購買の帳票（見積書・請求書・注文書など）に共通するモデルと計算。

消費税はインボイス制度に従い「1帳票・税率ごとに1回」端数処理する。
明細の金額は 数量×単価 の円未満切り捨て、価格はすべて税抜（外税）とする。
"""

from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal

from django.conf import settings
from django.db import models

from apps.audit.models import AuditedModel
from apps.core.models import TimeStampedModel
from apps.core.money import MoneyField, round_yen

from .models import TAX_RATE_PERCENT, TaxRate


class DocStatus(models.TextChoices):
    DRAFT = "draft", "下書き"
    ISSUED = "issued", "発行済"
    CANCELLED = "cancelled", "取消"


@dataclass
class TaxRow:
    rate: str
    base: Decimal
    tax: Decimal

    @property
    def label(self) -> str:
        return TaxRate(self.rate).label

    @property
    def is_reduced(self) -> bool:
        return self.rate == TaxRate.REDUCED

    def as_dict(self) -> dict:
        return {"rate": self.rate, "base": str(self.base), "tax": str(self.tax)}


def line_amount(quantity: Decimal, unit_price: Decimal) -> Decimal:
    value = Decimal(quantity or 0) * Decimal(unit_price or 0)
    sign = -1 if value < 0 else 1
    return abs(value).quantize(Decimal("1"), rounding=ROUND_FLOOR) * sign


def summarize_tax(lines, rounding: str) -> list[TaxRow]:
    """税率ごとの対象額と消費税額（税率ごとに1回端数処理）。"""
    bases: dict[str, Decimal] = {}
    for line in lines:
        bases[line.tax_rate] = bases.get(line.tax_rate, Decimal(0)) + line.amount
    rows = []
    for rate in TaxRate:
        if rate in bases:
            percent = TAX_RATE_PERCENT.get(rate, 0)
            rows.append(TaxRow(rate, bases[rate], round_yen(bases[rate] * percent / 100, rounding)))
    return rows


class TradeDocument(AuditedModel, TimeStampedModel):
    """帳票の共通項目。番号は発行時に採番する（下書きは番号なし）。"""

    number_key = ""
    title = ""

    number = models.CharField("番号", max_length=30, null=True, blank=True, unique=True)
    status = models.CharField("状態", max_length=20, choices=DocStatus.choices, default=DocStatus.DRAFT)
    partner = models.ForeignKey(
        "masters.Partner", verbose_name="取引先", on_delete=models.PROTECT, related_name="+"
    )
    issue_date = models.DateField("発行日")
    subject = models.CharField("件名", max_length=200, blank=True)
    notes = models.TextField("備考", blank=True)
    department = models.ForeignKey(
        "masters.Department",
        verbose_name="部門",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    project = models.ForeignKey(
        "masters.Project",
        verbose_name="プロジェクト",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    subtotal = MoneyField("小計（税抜）")
    tax_total = MoneyField("消費税額")
    total = MoneyField("合計（税込）")
    tax_summary = models.JSONField("税率別内訳", default=list, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="作成者", null=True, on_delete=models.PROTECT, related_name="+"
    )
    issued_at = models.DateTimeField("発行日時", null=True, blank=True)
    cancelled_at = models.DateTimeField("取消日時", null=True, blank=True)
    cancel_reason = models.CharField("取消理由", max_length=200, blank=True)
    pdf_file = models.FileField("発行時PDF", upload_to="issued/%Y/%m/", blank=True)
    pdf_sha256 = models.CharField("PDFハッシュ(SHA-256)", max_length=64, blank=True)

    class Meta:
        abstract = True

    def __str__(self) -> str:
        return f"{self.title} {self.number or '（下書き）'} {self.partner.name}"

    @property
    def is_draft(self) -> bool:
        return self.status == DocStatus.DRAFT

    def tax_rows(self) -> list[TaxRow]:
        return [TaxRow(r["rate"], Decimal(r["base"]), Decimal(r["tax"])) for r in self.tax_summary]

    @property
    def has_reduced_rate(self) -> bool:
        return any(r["rate"] == TaxRate.REDUCED for r in self.tax_summary)

    def recalculate(self, rounding: str) -> None:
        lines = list(self.lines.all())
        rows = summarize_tax(lines, rounding)
        self.subtotal = sum((r.base for r in rows), Decimal(0))
        self.tax_total = sum((r.tax for r in rows), Decimal(0))
        self.total = self.subtotal + self.tax_total
        self.tax_summary = [r.as_dict() for r in rows]


class TradeLine(models.Model):
    sort_order = models.PositiveSmallIntegerField("順序", default=0)
    item = models.ForeignKey(
        "masters.Item", verbose_name="品目", null=True, blank=True, on_delete=models.PROTECT
    )
    transaction_date = models.DateField("取引日", null=True, blank=True)
    description = models.CharField("品名・内容", max_length=255)
    quantity = models.DecimalField("数量", max_digits=12, decimal_places=3, default=1)
    unit = models.CharField("単位", max_length=10, blank=True)
    unit_price = models.DecimalField("単価", max_digits=15, decimal_places=2, default=0)
    tax_rate = models.CharField("税率", max_length=10, choices=TaxRate.choices, default=TaxRate.STANDARD)
    amount = MoneyField("金額")

    class Meta:
        abstract = True
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:
        return self.description

    def save(self, *args, **kwargs):
        self.amount = line_amount(self.quantity, self.unit_price)
        super().save(*args, **kwargs)
