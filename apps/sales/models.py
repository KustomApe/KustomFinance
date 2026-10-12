from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum

from apps.audit.models import AuditedModel
from apps.core.models import TimeStampedModel
from apps.core.money import MoneyField
from apps.masters.documents import DocStatus, TradeDocument, TradeLine


class Estimate(TradeDocument):
    number_key = "estimate"
    title = "見積書"

    valid_until = models.DateField("有効期限", null=True, blank=True)
    delivery_terms = models.CharField("納期・納入条件", max_length=200, blank=True)

    class Meta:
        verbose_name = "見積書"
        verbose_name_plural = "見積書"
        ordering = ["-issue_date", "-id"]


class EstimateLine(TradeLine):
    document = models.ForeignKey(Estimate, on_delete=models.CASCADE, related_name="lines")

    class Meta(TradeLine.Meta):
        pass


class SalesOrder(TradeDocument):
    number_key = "sales_order"
    title = "受注"

    estimate = models.ForeignKey(
        Estimate,
        verbose_name="見積書",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="orders",
    )
    customer_order_number = models.CharField("先方注文番号", max_length=50, blank=True)
    delivery_date = models.DateField("納期", null=True, blank=True)

    class Meta:
        verbose_name = "受注"
        verbose_name_plural = "受注"
        ordering = ["-issue_date", "-id"]


class SalesOrderLine(TradeLine):
    document = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name="lines")

    class Meta(TradeLine.Meta):
        pass


class Invoice(TradeDocument):
    """請求書（適格請求書）。発行時に売上仕訳を計上し、取消時は取消仕訳を計上する。"""

    number_key = "invoice"
    title = "請求書"

    order = models.ForeignKey(
        SalesOrder,
        verbose_name="受注",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invoices",
    )
    sales_date = models.DateField("売上計上日", null=True, blank=True, help_text="空欄なら発行日")
    due_date = models.DateField(
        "支払期日", null=True, blank=True, help_text="空欄なら取引先の支払条件から計算"
    )
    journal = models.OneToOneField(
        "ledger.Journal",
        verbose_name="売上仕訳",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )

    class Meta:
        verbose_name = "請求書"
        verbose_name_plural = "請求書"
        ordering = ["-issue_date", "-id"]

    @property
    def paid_amount(self) -> Decimal:
        return self.allocations.exclude(receipt__status=Receipt.Status.CANCELLED).aggregate(
            s=Sum("amount", default=Decimal(0))
        )["s"]

    @property
    def outstanding(self) -> Decimal:
        if self.status != DocStatus.ISSUED:
            return Decimal(0)
        return self.total - self.paid_amount

    @property
    def payment_status(self) -> str:
        if self.status != DocStatus.ISSUED:
            return ""
        paid = self.paid_amount
        if paid >= self.total:
            return "入金済"
        return "一部入金" if paid else "未入金"


class InvoiceLine(TradeLine):
    document = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")

    class Meta(TradeLine.Meta):
        pass


class Delivery(TradeDocument):
    number_key = "delivery"
    title = "納品書"

    order = models.ForeignKey(
        SalesOrder,
        verbose_name="受注",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="deliveries",
    )
    invoice = models.ForeignKey(
        Invoice,
        verbose_name="請求書",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="deliveries",
    )

    class Meta:
        verbose_name = "納品書"
        verbose_name_plural = "納品書"
        ordering = ["-issue_date", "-id"]


class DeliveryLine(TradeLine):
    document = models.ForeignKey(Delivery, on_delete=models.CASCADE, related_name="lines")

    class Meta(TradeLine.Meta):
        pass


class Receipt(AuditedModel, TimeStampedModel):
    """入金。請求書への消込を伴う。"""

    class Status(models.TextChoices):
        ACTIVE = "active", "有効"
        CANCELLED = "cancelled", "取消"

    number = models.CharField("入金番号", max_length=30, unique=True)
    status = models.CharField("状態", max_length=20, choices=Status.choices, default=Status.ACTIVE)
    date = models.DateField("入金日")
    partner = models.ForeignKey(
        "masters.Partner", verbose_name="取引先", on_delete=models.PROTECT, related_name="+"
    )
    deposit_account = models.ForeignKey(
        "ledger.Account", verbose_name="入金口座", on_delete=models.PROTECT, related_name="+"
    )
    deposit_sub_account = models.ForeignKey(
        "ledger.SubAccount",
        verbose_name="補助科目",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    amount = MoneyField("入金額")
    fee = MoneyField("振込手数料（当社負担）")
    memo = models.CharField("メモ", max_length=200, blank=True)
    journal = models.OneToOneField(
        "ledger.Journal",
        verbose_name="入金仕訳",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="登録者", null=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        verbose_name = "入金"
        verbose_name_plural = "入金"
        ordering = ["-date", "-id"]

    def __str__(self) -> str:
        return f"入金 {self.number} {self.partner.name}"

    @property
    def allocated_total(self) -> Decimal:
        return sum((a.amount for a in self.allocations.all()), Decimal(0))

    @property
    def advance_amount(self) -> Decimal:
        """請求書に消し込まなかった額（前受金）。"""
        return self.amount + self.fee - self.allocated_total


class ReceiptAllocation(models.Model):
    receipt = models.ForeignKey(Receipt, on_delete=models.PROTECT, related_name="allocations")
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="allocations")
    amount = MoneyField("消込額")

    class Meta:
        verbose_name = "入金消込"
        verbose_name_plural = "入金消込"
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="allocation_amount_positive")
        ]

    def __str__(self) -> str:
        return f"{self.receipt.number} → {self.invoice.number}: {self.amount}"
