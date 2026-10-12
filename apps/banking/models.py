from django.conf import settings
from django.db import models

from apps.audit.models import AuditedModel
from apps.core.models import TimeStampedModel
from apps.core.money import MoneyField


class BankAccount(AuditedModel, TimeStampedModel):
    name = models.CharField("口座名", max_length=100, help_text="例: ○○銀行 本店 普通")
    account = models.ForeignKey(
        "ledger.Account", verbose_name="勘定科目", on_delete=models.PROTECT, related_name="+"
    )
    sub_account = models.ForeignKey(
        "ledger.SubAccount",
        verbose_name="補助科目",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    bank_name = models.CharField("銀行名", max_length=100, blank=True)
    branch_name = models.CharField("支店名", max_length=100, blank=True)
    account_number = models.CharField("口座番号", max_length=20, blank=True)
    import_profile = models.ForeignKey(
        "ImportProfile", verbose_name="明細CSVの形式", null=True, blank=True, on_delete=models.PROTECT
    )
    is_active = models.BooleanField("有効", default=True)

    class Meta:
        verbose_name = "銀行口座"
        verbose_name_plural = "銀行口座"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class ImportProfile(AuditedModel, TimeStampedModel):
    """明細CSVの列の対応。列番号は1から数える（0 = その列なし）。"""

    name = models.CharField("名称", max_length=100, unique=True)
    skip_rows = models.PositiveSmallIntegerField("読み飛ばす先頭行数", default=1)
    date_column = models.PositiveSmallIntegerField("日付の列", default=1)
    description_column = models.PositiveSmallIntegerField("摘要の列", default=2)
    withdrawal_column = models.PositiveSmallIntegerField("出金額の列", default=3)
    deposit_column = models.PositiveSmallIntegerField("入金額の列", default=4)
    balance_column = models.PositiveSmallIntegerField("残高の列", default=5)
    amount_column = models.PositiveSmallIntegerField(
        "金額の列（符号付き）",
        default=0,
        help_text="入出金が1列（出金がマイナス）の場合に指定。出金・入金の列は0にします。",
    )

    class Meta:
        verbose_name = "明細CSV形式"
        verbose_name_plural = "明細CSV形式"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class ImportBatch(models.Model):
    bank_account = models.ForeignKey(BankAccount, on_delete=models.PROTECT, related_name="batches")
    file_name = models.CharField("ファイル名", max_length=255)
    file_sha256 = models.CharField("ファイルハッシュ", max_length=64)
    imported = models.PositiveIntegerField("取込件数", default=0)
    skipped = models.PositiveIntegerField("重複スキップ件数", default=0)
    created_at = models.DateTimeField("取込日時", auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        verbose_name = "明細取込"
        verbose_name_plural = "明細取込"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.bank_account} {self.file_name}"


class BankTransaction(models.Model):
    class Status(models.TextChoices):
        UNPROCESSED = "unprocessed", "未処理"
        DONE = "done", "処理済"
        IGNORED = "ignored", "対象外"

    bank_account = models.ForeignKey(BankAccount, on_delete=models.PROTECT, related_name="transactions")
    batch = models.ForeignKey(ImportBatch, on_delete=models.PROTECT, related_name="transactions")
    date = models.DateField("日付", db_index=True)
    description = models.CharField("摘要", max_length=255)
    deposit = MoneyField("入金")
    withdrawal = MoneyField("出金")
    balance = MoneyField("残高", null=True, blank=True, default=None)
    fingerprint = models.CharField("重複判定キー", max_length=64)
    status = models.CharField("状態", max_length=20, choices=Status.choices, default=Status.UNPROCESSED)
    journal = models.ForeignKey(
        "ledger.Journal",
        verbose_name="仕訳",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    note = models.CharField("メモ", max_length=200, blank=True)

    class Meta:
        verbose_name = "銀行明細"
        verbose_name_plural = "銀行明細"
        ordering = ["date", "id"]
        constraints = [
            models.UniqueConstraint(fields=["bank_account", "fingerprint"], name="unique_bank_transaction")
        ]

    def __str__(self) -> str:
        return f"{self.date} {self.description} {self.deposit or -self.withdrawal}"

    @property
    def amount(self):
        return self.deposit - self.withdrawal


class BankRule(AuditedModel, TimeStampedModel):
    """摘要のキーワードから仕訳を提案するルール。"""

    class Direction(models.TextChoices):
        ANY = "any", "入出金とも"
        DEPOSIT = "deposit", "入金のみ"
        WITHDRAWAL = "withdrawal", "出金のみ"

    keyword = models.CharField(
        "摘要に含む文字", max_length=100, help_text="半角・全角、大文字・小文字は区別しません"
    )
    direction = models.CharField("入出金", max_length=20, choices=Direction.choices, default=Direction.ANY)
    account = models.ForeignKey(
        "ledger.Account", verbose_name="相手科目", on_delete=models.PROTECT, related_name="+"
    )
    tax_category = models.ForeignKey(
        "ledger.TaxCategory", verbose_name="税区分", null=True, blank=True, on_delete=models.PROTECT
    )
    partner = models.ForeignKey(
        "masters.Partner",
        verbose_name="取引先",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    description = models.CharField("仕訳の摘要", max_length=200, blank=True, help_text="空欄なら明細の摘要")
    priority = models.PositiveSmallIntegerField("優先順位", default=100, help_text="小さいほど優先")
    is_active = models.BooleanField("有効", default=True)

    class Meta:
        verbose_name = "自動仕訳ルール"
        verbose_name_plural = "自動仕訳ルール"
        ordering = ["priority", "id"]

    def __str__(self) -> str:
        return f"「{self.keyword}」→ {self.account}"
