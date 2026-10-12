from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from apps.audit.models import AuditedModel
from apps.core.models import TimeStampedModel
from apps.core.money import MoneyField


class AccountType(models.TextChoices):
    ASSET = "asset", "資産"
    LIABILITY = "liability", "負債"
    EQUITY = "equity", "純資産"
    REVENUE = "revenue", "収益"
    EXPENSE = "expense", "費用"


class Section(models.TextChoices):
    """決算書の表示区分。並び順は決算書の順序。"""

    CURRENT_ASSETS = "current_assets", "流動資産"
    FIXED_ASSETS = "fixed_assets", "固定資産"
    DEFERRED_ASSETS = "deferred_assets", "繰延資産"
    CURRENT_LIABILITIES = "current_liabilities", "流動負債"
    LONG_TERM_LIABILITIES = "long_term_liabilities", "固定負債"
    EQUITY = "equity", "純資産"
    SALES = "sales", "売上高"
    COST_OF_SALES = "cost_of_sales", "売上原価"
    SGA = "sga", "販売費及び一般管理費"
    NON_OPERATING_INCOME = "non_operating_income", "営業外収益"
    NON_OPERATING_EXPENSES = "non_operating_expenses", "営業外費用"
    EXTRAORDINARY_INCOME = "extraordinary_income", "特別利益"
    EXTRAORDINARY_LOSSES = "extraordinary_losses", "特別損失"
    INCOME_TAXES = "income_taxes", "法人税等"


SECTION_TYPES = {
    Section.CURRENT_ASSETS: AccountType.ASSET,
    Section.FIXED_ASSETS: AccountType.ASSET,
    Section.DEFERRED_ASSETS: AccountType.ASSET,
    Section.CURRENT_LIABILITIES: AccountType.LIABILITY,
    Section.LONG_TERM_LIABILITIES: AccountType.LIABILITY,
    Section.EQUITY: AccountType.EQUITY,
    Section.SALES: AccountType.REVENUE,
    Section.NON_OPERATING_INCOME: AccountType.REVENUE,
    Section.EXTRAORDINARY_INCOME: AccountType.REVENUE,
    Section.COST_OF_SALES: AccountType.EXPENSE,
    Section.SGA: AccountType.EXPENSE,
    Section.NON_OPERATING_EXPENSES: AccountType.EXPENSE,
    Section.EXTRAORDINARY_LOSSES: AccountType.EXPENSE,
    Section.INCOME_TAXES: AccountType.EXPENSE,
}
PL_SECTIONS = [s for s, t in SECTION_TYPES.items() if t in (AccountType.REVENUE, AccountType.EXPENSE)]
BS_SECTIONS = [s for s in Section if s not in PL_SECTIONS]
SECTION_ORDER = {s: i for i, s in enumerate(Section)}


class Side(models.TextChoices):
    DEBIT = "D", "借方"
    CREDIT = "C", "貸方"


class TaxKind(models.TextChoices):
    OUT_OF_SCOPE = "out", "対象外・不課税"
    TAXABLE_SALES = "taxable_sales", "課税売上"
    EXEMPT_SALES = "exempt_sales", "非課税売上"
    EXPORT_SALES = "export_sales", "輸出免税売上"
    TAXABLE_PURCHASE = "taxable_purchase", "課税仕入"
    EXEMPT_PURCHASE = "exempt_purchase", "非課税仕入"


class TaxCategory(AuditedModel, TimeStampedModel):
    """税区分。経過措置（免税事業者等からの仕入の80%/50%控除）は deductible_percent で表す。"""

    code = models.CharField("コード", max_length=20, unique=True)
    name = models.CharField("名称", max_length=50)
    kind = models.CharField("種類", max_length=20, choices=TaxKind.choices)
    rate = models.PositiveSmallIntegerField("税率(%)", default=0)
    is_reduced = models.BooleanField("軽減税率", default=False)
    deductible_percent = models.PositiveSmallIntegerField("控除割合(%)", default=100)
    sort_order = models.PositiveSmallIntegerField("表示順", default=0)
    is_active = models.BooleanField("有効", default=True)

    class Meta:
        verbose_name = "税区分"
        verbose_name_plural = "税区分"
        ordering = ["sort_order", "code"]

    def __str__(self) -> str:
        return self.name

    @property
    def generates_tax_line(self) -> bool:
        return self.rate > 0 and self.kind in (TaxKind.TAXABLE_SALES, TaxKind.TAXABLE_PURCHASE)


class Account(AuditedModel, TimeStampedModel):
    """勘定科目。system_key はプログラムから参照する主要科目の識別子。"""

    code = models.CharField("コード", max_length=10, unique=True)
    name = models.CharField("科目名", max_length=50, unique=True)
    section = models.CharField("区分", max_length=30, choices=Section.choices)
    default_tax_category = models.ForeignKey(
        TaxCategory, verbose_name="既定の税区分", null=True, blank=True, on_delete=models.PROTECT
    )
    system_key = models.CharField("システムキー", max_length=30, blank=True, editable=False)
    is_active = models.BooleanField("有効", default=True)

    class Meta:
        verbose_name = "勘定科目"
        verbose_name_plural = "勘定科目"
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(
                fields=["system_key"], condition=~models.Q(system_key=""), name="unique_account_system_key"
            )
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def account_type(self) -> str:
        return SECTION_TYPES[self.section]

    @property
    def normal_side(self) -> str:
        if self.account_type in (AccountType.ASSET, AccountType.EXPENSE):
            return Side.DEBIT
        return Side.CREDIT

    @property
    def is_pl(self) -> bool:
        return self.section in PL_SECTIONS

    @classmethod
    def by_key(cls, key: str) -> "Account":
        return cls.objects.get(system_key=key)


class SubAccount(AuditedModel, TimeStampedModel):
    account = models.ForeignKey(
        Account, verbose_name="勘定科目", on_delete=models.PROTECT, related_name="sub_accounts"
    )
    code = models.CharField("コード", max_length=10, blank=True)
    name = models.CharField("補助科目名", max_length=50)
    is_active = models.BooleanField("有効", default=True)

    class Meta:
        verbose_name = "補助科目"
        verbose_name_plural = "補助科目"
        ordering = ["account__code", "code", "name"]
        constraints = [models.UniqueConstraint(fields=["account", "name"], name="unique_sub_account_name")]

    def __str__(self) -> str:
        return f"{self.account.name} / {self.name}"


class JournalSource(models.TextChoices):
    MANUAL = "manual", "手入力"
    OPENING = "opening", "開始残高"
    REVERSAL = "reversal", "取消"
    SALES = "sales", "販売"
    PURCHASE = "purchase", "購買"
    EXPENSE = "expense", "経費"
    BANK = "bank", "銀行"
    ASSET = "asset", "固定資産"


class Journal(AuditedModel, TimeStampedModel):
    """仕訳。登録後は変更・削除不可（DBトリガー）。訂正は取消仕訳で行う。"""

    number = models.CharField("仕訳番号", max_length=30, unique=True)
    date = models.DateField("取引日", db_index=True)
    description = models.CharField("摘要", max_length=255, blank=True)
    source = models.CharField(
        "発生元", max_length=20, choices=JournalSource.choices, default=JournalSource.MANUAL
    )
    source_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.PROTECT)
    source_id = models.PositiveBigIntegerField(null=True, blank=True)
    source_object = GenericForeignKey("source_type", "source_id")
    reverses = models.OneToOneField(
        "self",
        verbose_name="取消対象",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reversed_by",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="登録者", null=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        verbose_name = "仕訳"
        verbose_name_plural = "仕訳"
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["source_type", "source_id"])]

    def __str__(self) -> str:
        return f"{self.number} {self.description}".strip()

    @property
    def is_reversed(self) -> bool:
        return hasattr(self, "reversed_by")

    @property
    def total(self):
        return sum(line.amount for line in self.lines.all() if line.side == Side.DEBIT)


class JournalLine(models.Model):
    """仕訳明細。金額は税抜（税抜経理）。消費税は tax_base を持つ別の行に計上する。"""

    journal = models.ForeignKey(Journal, on_delete=models.PROTECT, related_name="lines")
    line_no = models.PositiveSmallIntegerField("行番号")
    side = models.CharField("貸借", max_length=1, choices=Side.choices)
    account = models.ForeignKey(
        Account, verbose_name="勘定科目", on_delete=models.PROTECT, related_name="lines"
    )
    sub_account = models.ForeignKey(
        SubAccount,
        verbose_name="補助科目",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="lines",
    )
    amount = MoneyField("金額")
    tax_category = models.ForeignKey(
        TaxCategory, verbose_name="税区分", null=True, blank=True, on_delete=models.PROTECT
    )
    tax_amount = MoneyField("消費税額")
    tax_base = models.ForeignKey(
        "self",
        verbose_name="消費税の元明細",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    description = models.CharField("摘要", max_length=255, blank=True)

    class Meta:
        verbose_name = "仕訳明細"
        verbose_name_plural = "仕訳明細"
        ordering = ["journal", "line_no"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gte=0), name="journal_line_amount_non_negative"
            ),
            models.UniqueConstraint(fields=["journal", "line_no"], name="unique_journal_line_no"),
        ]

    def __str__(self) -> str:
        return f"{self.get_side_display()} {self.account} {self.amount}"

    @property
    def gross_amount(self):
        return self.amount + self.tax_amount
