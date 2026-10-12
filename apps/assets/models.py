from django.conf import settings
from django.db import models

from apps.audit.models import AuditedModel
from apps.core.models import TimeStampedModel
from apps.core.money import MoneyField


class DepreciationRate(AuditedModel, TimeStampedModel):
    """耐用年数ごとの償却率（定額法・200%定率法）。

    初期値は計算式から求めた値です。国税庁「減価償却資産の償却率等表」と照合して利用してください。
    """

    useful_life = models.PositiveSmallIntegerField("耐用年数", unique=True)
    straight_line_rate = models.DecimalField("定額法 償却率", max_digits=5, decimal_places=3)
    declining_rate = models.DecimalField("定率法 償却率", max_digits=5, decimal_places=3)
    revised_rate = models.DecimalField("定率法 改定償却率", max_digits=5, decimal_places=3)
    guarantee_rate = models.DecimalField("定率法 保証率", max_digits=6, decimal_places=5)

    class Meta:
        verbose_name = "償却率"
        verbose_name_plural = "償却率"
        ordering = ["useful_life"]

    def __str__(self) -> str:
        return f"耐用年数{self.useful_life}年"


class FixedAsset(AuditedModel, TimeStampedModel):
    class Method(models.TextChoices):
        STRAIGHT_LINE = "straight_line", "定額法"
        DECLINING = "declining", "定率法"
        LUMP_SUM = "lump_sum", "一括償却（3年均等）"
        IMMEDIATE = "immediate", "少額減価償却資産（即時償却）"
        NONE = "none", "非償却（土地など）"

    class Status(models.TextChoices):
        ACTIVE = "active", "使用中"
        DISPOSED = "disposed", "除却済"

    number = models.CharField("資産番号", max_length=30, unique=True)
    name = models.CharField("資産名", max_length=200)
    account = models.ForeignKey(
        "ledger.Account", verbose_name="勘定科目", on_delete=models.PROTECT, related_name="+"
    )
    acquisition_date = models.DateField("取得日")
    service_date = models.DateField("事業供用日")
    acquisition_cost = MoneyField("取得価額")
    quantity = models.PositiveIntegerField("数量", default=1)
    method = models.CharField("償却方法", max_length=20, choices=Method.choices, default=Method.STRAIGHT_LINE)
    useful_life = models.PositiveSmallIntegerField("耐用年数", null=True, blank=True)
    opening_date = models.DateField(
        "期首残高の基準日",
        null=True,
        blank=True,
        help_text="他システムから移行する場合、償却累計額を入力した時点の期首日",
    )
    opening_accumulated = MoneyField("移行時の償却累計額", default=0)
    revised_base = MoneyField(
        "改定取得価額",
        null=True,
        blank=True,
        default=None,
        help_text="定率法で改定償却率に切り替えた年度の期首帳簿価額",
    )
    department = models.ForeignKey(
        "masters.Department",
        verbose_name="部門",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    location = models.CharField("設置場所", max_length=200, blank=True)
    notes = models.TextField("備考", blank=True)
    status = models.CharField("状態", max_length=20, choices=Status.choices, default=Status.ACTIVE)
    disposal_date = models.DateField("除却日", null=True, blank=True)
    disposal_journal = models.OneToOneField(
        "ledger.Journal",
        verbose_name="除却仕訳",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )

    class Meta:
        verbose_name = "固定資産"
        verbose_name_plural = "固定資産"
        ordering = ["number"]

    def __str__(self) -> str:
        return f"{self.number} {self.name}"

    @property
    def posted_total(self):
        return self.entries.aggregate(s=models.Sum("amount", default=0))["s"]

    @property
    def book_value(self):
        return self.acquisition_cost - self.opening_accumulated - self.posted_total


class DepreciationEntry(models.Model):
    asset = models.ForeignKey(FixedAsset, on_delete=models.PROTECT, related_name="entries")
    fiscal_year_start = models.DateField("事業年度の期首")
    date = models.DateField("計上日")
    amount = MoneyField("償却額")
    journal = models.ForeignKey("ledger.Journal", on_delete=models.PROTECT, related_name="+")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        verbose_name = "償却実績"
        verbose_name_plural = "償却実績"
        ordering = ["date", "id"]

    def __str__(self) -> str:
        return f"{self.asset.number} {self.date} {self.amount}"
