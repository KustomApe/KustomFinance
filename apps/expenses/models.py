from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.audit.models import AuditedModel
from apps.core.models import TimeStampedModel, invoice_registration_validator
from apps.core.money import MoneyField


class ExpenseClaim(AuditedModel, TimeStampedModel):
    """経費精算申請。申請→承認（仕訳計上: 経費 / 未払金）→精算（未払金 / 預金）。"""

    class Status(models.TextChoices):
        DRAFT = "draft", "下書き"
        SUBMITTED = "submitted", "承認待ち"
        REJECTED = "rejected", "差戻し"
        APPROVED = "approved", "承認済（未精算）"
        PAID = "paid", "精算済"
        CANCELLED = "cancelled", "取消"

    number = models.CharField("申請番号", max_length=30, null=True, blank=True, unique=True)
    status = models.CharField("状態", max_length=20, choices=Status.choices, default=Status.DRAFT)
    applicant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="申請者",
        on_delete=models.PROTECT,
        related_name="expense_claims",
    )
    title = models.CharField("件名", max_length=200)
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
    total = MoneyField("合計")
    submitted_at = models.DateTimeField("申請日時", null=True, blank=True)
    approver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="承認者",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    approved_at = models.DateTimeField("承認日時", null=True, blank=True)
    reject_reason = models.CharField("差戻し理由", max_length=200, blank=True)
    journal = models.OneToOneField(
        "ledger.Journal",
        verbose_name="計上仕訳",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    paid_date = models.DateField("精算日", null=True, blank=True)
    payment_journal = models.OneToOneField(
        "ledger.Journal",
        verbose_name="精算仕訳",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )

    class Meta:
        verbose_name = "経費精算"
        verbose_name_plural = "経費精算"
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"経費精算 {self.number or '（下書き）'} {self.title}"

    @property
    def is_editable(self) -> bool:
        return self.status in (self.Status.DRAFT, self.Status.REJECTED)

    def recalculate(self) -> None:
        self.total = sum((line.amount for line in self.lines.all()), Decimal(0))


class ExpenseLine(models.Model):
    claim = models.ForeignKey(ExpenseClaim, on_delete=models.CASCADE, related_name="lines")
    date = models.DateField("利用日")
    account = models.ForeignKey(
        "ledger.Account", verbose_name="勘定科目", on_delete=models.PROTECT, related_name="+"
    )
    tax_category = models.ForeignKey("ledger.TaxCategory", verbose_name="税区分", on_delete=models.PROTECT)
    amount = MoneyField("金額（税込）")
    payee = models.CharField("支払先", max_length=100)
    payee_registration_number = models.CharField(
        "支払先の登録番号",
        max_length=14,
        blank=True,
        validators=[invoice_registration_validator],
        help_text="領収書に記載の T+13桁",
    )
    invoice_exempt = models.BooleanField(
        "インボイス不要の特例",
        default=False,
        help_text="公共交通機関（3万円未満）・出張旅費・自動販売機など、帳簿の記載のみで控除できる取引",
    )
    description = models.CharField("内容", max_length=200)
    receipt = models.FileField("領収書", upload_to="receipts/%Y/%m/", blank=True)
    receipt_sha256 = models.CharField("領収書ハッシュ(SHA-256)", max_length=64, blank=True)

    class Meta:
        verbose_name = "経費明細"
        verbose_name_plural = "経費明細"
        ordering = ["date", "id"]

    def __str__(self) -> str:
        return f"{self.date} {self.payee} {self.amount}"

    def save(self, *args, **kwargs):
        if self.receipt and not self.receipt._committed:
            from apps.core.files import file_sha256

            self.receipt_sha256 = file_sha256(self.receipt)
        elif not self.receipt:
            self.receipt_sha256 = ""
        super().save(*args, **kwargs)
