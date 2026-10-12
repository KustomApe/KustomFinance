import datetime

from django import forms

from apps.core.forms import DateInput, StyledFormMixin
from apps.ledger.models import Account, Section, SubAccount, TaxCategory, TaxKind
from apps.sales.forms import deposit_accounts

from .models import ExpenseClaim, ExpenseLine


class ClaimForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ExpenseClaim
        fields = ["title", "department", "project"]


class LineForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ExpenseLine
        fields = [
            "date",
            "account",
            "tax_category",
            "amount",
            "payee",
            "payee_registration_number",
            "invoice_exempt",
            "description",
            "receipt",
        ]
        widgets = {
            "date": DateInput(),
            "receipt": forms.ClearableFileInput(attrs={"accept": "image/*,video/*,.heic,.heif,.pdf"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["account"].queryset = Account.objects.filter(
            is_active=True, section__in=[Section.SGA, Section.COST_OF_SALES, Section.NON_OPERATING_EXPENSES]
        )
        self.fields["tax_category"].queryset = TaxCategory.objects.filter(
            is_active=True,
            kind__in=[TaxKind.TAXABLE_PURCHASE, TaxKind.EXEMPT_PURCHASE, TaxKind.OUT_OF_SCOPE],
            deductible_percent=100,
        )
        self.fields["amount"].widget.attrs["min"] = 1
        if not self.instance.pk:
            # 空の追加行が「変更あり」と判定されないよう、モデルの既定値0を初期値にしない
            self.initial["amount"] = None

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount is not None and amount <= 0:
            raise forms.ValidationError("金額は1円以上で入力してください。")
        return amount


LineFormSet = forms.inlineformset_factory(ExpenseClaim, ExpenseLine, form=LineForm, extra=3, can_delete=True)


class ApproveForm(StyledFormMixin, forms.Form):
    posting_date = forms.DateField(label="計上日", widget=DateInput(), initial=datetime.date.today)


class PayForm(StyledFormMixin, forms.Form):
    date = forms.DateField(label="精算日", widget=DateInput(), initial=datetime.date.today)
    account = forms.ModelChoiceField(deposit_accounts(), label="支払口座")
    sub_account = forms.ModelChoiceField(SubAccount.objects.all(), label="補助科目", required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["account"].queryset = deposit_accounts()
