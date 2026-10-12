from django import forms

from apps.core.forms import DateInput, StyledFormMixin
from apps.ledger.models import Account, SubAccount

from .models import Delivery, Estimate, Invoice, SalesOrder

COMMON = ["partner", "issue_date", "subject", "department", "project"]
NOTES_WIDGET = {"notes": forms.Textarea(attrs={"rows": 3}), "issue_date": DateInput()}


class EstimateForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Estimate
        fields = [*COMMON, "valid_until", "delivery_terms", "notes"]
        widgets = {**NOTES_WIDGET, "valid_until": DateInput()}


class SalesOrderForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = SalesOrder
        fields = [*COMMON, "customer_order_number", "delivery_date", "notes"]
        widgets = {**NOTES_WIDGET, "delivery_date": DateInput()}


class DeliveryForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Delivery
        fields = [*COMMON, "notes"]
        widgets = NOTES_WIDGET


class InvoiceForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Invoice
        fields = [*COMMON, "sales_date", "due_date", "notes"]
        widgets = {**NOTES_WIDGET, "sales_date": DateInput(), "due_date": DateInput()}


def deposit_accounts():
    return Account.objects.filter(system_key__in=["cash", "bank", "petty_cash"]) | Account.objects.filter(
        code__in=["1130", "1150"]
    )


class ReceiptForm(StyledFormMixin, forms.Form):
    date = forms.DateField(label="入金日", widget=DateInput())
    deposit_account = forms.ModelChoiceField(deposit_accounts(), label="入金口座")
    deposit_sub_account = forms.ModelChoiceField(SubAccount.objects.all(), label="補助科目", required=False)
    amount = forms.DecimalField(label="入金額", max_digits=15, decimal_places=0, min_value=1)
    fee = forms.DecimalField(
        label="振込手数料（当社負担）", max_digits=15, decimal_places=0, min_value=0, initial=0
    )
    memo = forms.CharField(label="メモ", max_length=200, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["deposit_account"].queryset = deposit_accounts()

    def clean(self):
        cleaned = super().clean()
        sub, account = cleaned.get("deposit_sub_account"), cleaned.get("deposit_account")
        if sub and account and sub.account_id != account.pk:
            self.add_error("deposit_sub_account", "入金口座の補助科目を選択してください。")
        return cleaned
