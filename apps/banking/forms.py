from django import forms

from apps.core.forms import StyledFormMixin
from apps.ledger.models import Account, TaxCategory
from apps.masters.models import Partner

from .models import BankAccount, BankRule, ImportProfile


class BankAccountForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = BankAccount
        fields = [
            "name",
            "account",
            "sub_account",
            "bank_name",
            "branch_name",
            "account_number",
            "import_profile",
            "is_active",
        ]

    def clean(self):
        cleaned = super().clean()
        sub, account = cleaned.get("sub_account"), cleaned.get("account")
        if sub and account and sub.account_id != account.pk:
            self.add_error("sub_account", "勘定科目の補助科目を選択してください。")
        return cleaned


class ImportProfileForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ImportProfile
        fields = [
            "name",
            "skip_rows",
            "date_column",
            "description_column",
            "withdrawal_column",
            "deposit_column",
            "amount_column",
            "balance_column",
        ]


class RuleForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = BankRule
        fields = [
            "keyword",
            "direction",
            "account",
            "tax_category",
            "partner",
            "description",
            "priority",
            "is_active",
        ]


class ImportForm(StyledFormMixin, forms.Form):
    bank_account = forms.ModelChoiceField(BankAccount.objects.filter(is_active=True), label="口座")
    file = forms.FileField(label="明細CSV")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["bank_account"].queryset = BankAccount.objects.filter(is_active=True)


class PostForm(forms.Form):
    account = forms.ModelChoiceField(Account.objects.filter(is_active=True))
    tax_category = forms.ModelChoiceField(TaxCategory.objects.filter(is_active=True), required=False)
    partner = forms.ModelChoiceField(Partner.objects.filter(is_active=True), required=False)
    description = forms.CharField(max_length=255, required=False)
