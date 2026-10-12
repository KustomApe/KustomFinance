from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum

from apps.audit.models import AuditedModel
from apps.core.models import TimeStampedModel, invoice_registration_validator
from apps.core.money import MoneyField
from apps.masters.documents import DocStatus, TradeDocument, TradeLine
from apps.masters.models import TaxRate


class PurchaseOrder(TradeDocument):
    """注文書（発注）。"""

    number_key = "purchase_order"
    title = "注文書"

    delivery_date = models.DateField("希望納期", null=True, blank=True)
    delivery_place = models.CharField("納品場所", max_length=200, blank=True)
    payment_terms = models.CharField("支払条件", max_length=200, blank=True)

    class Meta:
        verbose_name = "注文書"
        verbose_name_plural = "注文書"
        ordering = ["-issue_date", "-id"]


class PurchaseOrderLine(TradeLine):
    document = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="lines")

    class Meta(TradeLine.Meta):
        pass


class Bill(TradeDocument):
    """仕入先から受け取った請求書。「計上」（発行）で仕入仕訳を計上する。"""

    number_key = "bill"
    title = "仕入請求書"

    order = models.ForeignKey(
        PurchaseOrder,
        verbose_name="注文書",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="bills",
    )
    supplier_invoice_number = models.CharField("先方請求書番号", max_length=50, blank=True)
    supplier_registration_number = models.CharField(
        "先方の登録番号",
        max_length=14,
        blank=True,
        validators=[invoice_registration_validator],
        help_text="受け取った請求書に記載の登録番号。空欄なら取引先マスタの番号を使います。"
        "登録番号がない場合は経過措置（80%/50%控除）を適用します。",
    )
    purchase_date = models.DateField(
        "仕入計上日", null=True, blank=True, help_text="空欄なら発行日（請求日）"
    )
    due_date = models.DateField(
        "支払期日", null=True, blank=True, help_text="空欄なら取引先の支払条件から計算"
    )
    account = models.ForeignKey(
        "ledger.Account",
        verbose_name="計上科目",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        help_text="品目に仕入科目がない明細の計上先。空欄なら「仕入高」",
    )
    tax_10_override = MoneyField("請求書記載の消費税額（10%）", null=True, blank=True, default=None)
    tax_8_override = MoneyField("請求書記載の消費税額（8%軽減）", null=True, blank=True, default=None)
    attachment = models.FileField("受領した請求書ファイル", upload_to="received/%Y/%m/", blank=True)
    attachment_sha256 = models.CharField("受領ファイルハッシュ(SHA-256)", max_length=64, blank=True)
    journal = models.OneToOneField(
        "ledger.Journal",
        verbose_name="仕入仕訳",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )

    class Meta:
        verbose_name = "仕入請求書"
        verbose_name_plural = "仕入請求書"
        ordering = ["-issue_date", "-id"]

    def save(self, *args, **kwargs):
        if self.attachment and not self.attachment._committed:
            from .services import file_sha256

            self.attachment_sha256 = file_sha256(self.attachment)
        elif not self.attachment:
            self.attachment_sha256 = ""
        super().save(*args, **kwargs)

    def recalculate(self, rounding: str) -> None:
        """請求書に記載された税額がある場合はそれを優先する（先方の端数処理に合わせる）。"""
        super().recalculate(rounding)
        overrides = {TaxRate.STANDARD: self.tax_10_override, TaxRate.REDUCED: self.tax_8_override}
        for row in self.tax_summary:
            if overrides.get(row["rate"]) is not None:
                row["tax"] = str(overrides[row["rate"]])
        self.tax_total = sum((Decimal(r["tax"]) for r in self.tax_summary), Decimal(0))
        self.total = self.subtotal + self.tax_total

    @property
    def paid_amount(self) -> Decimal:
        return self.allocations.exclude(payment__status=Payment.Status.CANCELLED).aggregate(
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
            return "支払済"
        return "一部支払" if paid else "未払"


class BillLine(TradeLine):
    document = models.ForeignKey(Bill, on_delete=models.CASCADE, related_name="lines")

    class Meta(TradeLine.Meta):
        pass


class GoodsReceipt(TradeDocument):
    """検収（納品の受入）。複数の検収をまとめて仕入請求書を作成できる。"""

    number_key = "goods_receipt"
    title = "検収書"

    order = models.ForeignKey(
        PurchaseOrder,
        verbose_name="注文書",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="receipts",
    )
    bill = models.ForeignKey(
        Bill,
        verbose_name="仕入請求書",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="goods_receipts",
    )

    class Meta:
        verbose_name = "検収"
        verbose_name_plural = "検収"
        ordering = ["-issue_date", "-id"]


class GoodsReceiptLine(TradeLine):
    document = models.ForeignKey(GoodsReceipt, on_delete=models.CASCADE, related_name="lines")

    class Meta(TradeLine.Meta):
        pass


class Payment(AuditedModel, TimeStampedModel):
    """支払。仕入請求書への消込を伴う。"""

    class Status(models.TextChoices):
        ACTIVE = "active", "有効"
        CANCELLED = "cancelled", "取消"

    number = models.CharField("支払番号", max_length=30, unique=True)
    status = models.CharField("状態", max_length=20, choices=Status.choices, default=Status.ACTIVE)
    date = models.DateField("支払日")
    partner = models.ForeignKey(
        "masters.Partner", verbose_name="支払先", on_delete=models.PROTECT, related_name="+"
    )
    pay_account = models.ForeignKey(
        "ledger.Account", verbose_name="支払口座", on_delete=models.PROTECT, related_name="+"
    )
    pay_sub_account = models.ForeignKey(
        "ledger.SubAccount",
        verbose_name="補助科目",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    amount = MoneyField("振込額")
    fee = MoneyField("振込手数料（当社負担）")
    deduction = MoneyField("先方負担手数料（差引額）")
    memo = models.CharField("メモ", max_length=200, blank=True)
    journal = models.OneToOneField(
        "ledger.Journal",
        verbose_name="支払仕訳",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="登録者", null=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        verbose_name = "支払"
        verbose_name_plural = "支払"
        ordering = ["-date", "-id"]

    def __str__(self) -> str:
        return f"支払 {self.number} {self.partner.name}"

    @property
    def allocated_total(self) -> Decimal:
        return sum((a.amount for a in self.allocations.all()), Decimal(0))

    @property
    def advance_amount(self) -> Decimal:
        """請求書に消し込まなかった額（前渡金）。"""
        return self.amount + self.deduction - self.allocated_total


class PaymentAllocation(models.Model):
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="allocations")
    bill = models.ForeignKey(Bill, on_delete=models.PROTECT, related_name="allocations")
    amount = MoneyField("消込額")

    class Meta:
        verbose_name = "支払消込"
        verbose_name_plural = "支払消込"
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="payment_allocation_positive")
        ]

    def __str__(self) -> str:
        return f"{self.payment.number} → {self.bill.number}: {self.amount}"
