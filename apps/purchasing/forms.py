from django import forms

from apps.core.forms import DateInput, StyledFormMixin
from apps.ledger.models import Account, SubAccount
from apps.sales.forms import deposit_accounts

from .models import Bill, GoodsReceipt, PurchaseOrder

COMMON = ["partner", "issue_date", "subject", "department", "project"]
WIDGETS = {"notes": forms.Textarea(attrs={"rows": 3}), "issue_date": DateInput()}


class PurchaseOrderForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = PurchaseOrder
        fields = [*COMMON, "delivery_date", "delivery_place", "payment_terms", "notes"]
        widgets = {**WIDGETS, "delivery_date": DateInput()}


class GoodsReceiptForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = GoodsReceipt
        fields = [*COMMON, "notes"]
        widgets = WIDGETS
        labels = {"issue_date": "検収日"}


class BillForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Bill
        fields = [
            *COMMON,
            "supplier_invoice_number",
            "supplier_registration_number",
            "purchase_date",
            "due_date",
            "account",
            "tax_10_override",
            "tax_8_override",
            "attachment",
            "notes",
        ]
        widgets = {**WIDGETS, "purchase_date": DateInput(), "due_date": DateInput()}
        labels = {"issue_date": "請求日"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["account"].queryset = Account.objects.filter(
            is_active=True,
            section__in=["cost_of_sales", "sga", "fixed_assets", "current_assets", "non_operating_expenses"],
        )


class PaymentForm(StyledFormMixin, forms.Form):
    date = forms.DateField(label="支払日", widget=DateInput())
    pay_account = forms.ModelChoiceField(deposit_accounts(), label="支払口座")
    pay_sub_account = forms.ModelChoiceField(SubAccount.objects.all(), label="補助科目", required=False)
    amount = forms.DecimalField(label="振込額", max_digits=15, decimal_places=0, min_value=1)
    fee = forms.DecimalField(
        label="振込手数料（当社負担）", max_digits=15, decimal_places=0, min_value=0, initial=0
    )
    deduction = forms.DecimalField(
        label="先方負担手数料（差引額）",
        max_digits=15,
        decimal_places=0,
        min_value=0,
        initial=0,
        help_text="請求額から振込手数料を差し引いて支払う場合の差引額",
    )
    memo = forms.CharField(label="メモ", max_length=200, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["pay_account"].queryset = deposit_accounts()

    def clean(self):
        cleaned = super().clean()
        sub, account = cleaned.get("pay_sub_account"), cleaned.get("pay_account")
        if sub and account and sub.account_id != account.pk:
            self.add_error("pay_sub_account", "支払口座の補助科目を選択してください。")
        return cleaned
