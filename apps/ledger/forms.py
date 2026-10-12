import datetime

from django import forms

from apps.core.forms import DateInput, StyledFormMixin
from apps.core.models import Company

from .models import Account, SubAccount, TaxCategory


class JournalHeaderForm(StyledFormMixin, forms.Form):
    date = forms.DateField(label="取引日", widget=DateInput())
    description = forms.CharField(label="摘要", max_length=255, required=False)
    is_opening = forms.BooleanField(label="開始残高として登録", required=False)


class JournalRowForm(forms.Form):
    """仕訳入力の1行（借方・貸方を横に並べた形式）。"""

    debit_account = forms.ModelChoiceField(Account.objects.all(), required=False)
    debit_sub_account = forms.ModelChoiceField(SubAccount.objects.all(), required=False)
    debit_tax_category = forms.ModelChoiceField(TaxCategory.objects.all(), required=False)
    debit_amount = forms.DecimalField(max_digits=15, decimal_places=0, min_value=0, required=False)
    credit_account = forms.ModelChoiceField(Account.objects.all(), required=False)
    credit_sub_account = forms.ModelChoiceField(SubAccount.objects.all(), required=False)
    credit_tax_category = forms.ModelChoiceField(TaxCategory.objects.all(), required=False)
    credit_amount = forms.DecimalField(max_digits=15, decimal_places=0, min_value=0, required=False)
    description = forms.CharField(max_length=255, required=False)

    def clean(self):
        cleaned = super().clean()
        for side, label in (("debit", "借方"), ("credit", "貸方")):
            account, amount = cleaned.get(f"{side}_account"), cleaned.get(f"{side}_amount")
            if amount and not account:
                raise forms.ValidationError(f"{label}の勘定科目を選択してください。")
            if account and not amount:
                raise forms.ValidationError(f"{label}の金額を入力してください。")
        return cleaned


JournalRowFormSet = forms.formset_factory(JournalRowForm, extra=0, min_num=1)


class ReverseForm(StyledFormMixin, forms.Form):
    date = forms.DateField(label="取消日", widget=DateInput(), initial=datetime.date.today)
    reason = forms.CharField(label="取消理由", max_length=200)


class PeriodFilterForm(StyledFormMixin, forms.Form):
    date_from = forms.DateField(label="開始日", widget=DateInput())
    date_to = forms.DateField(label="終了日", widget=DateInput())

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("date_from") and cleaned.get("date_to") and cleaned["date_from"] > cleaned["date_to"]:
            raise forms.ValidationError("開始日は終了日以前の日付にしてください。")
        return cleaned


class AccountForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Account
        fields = ["code", "name", "section", "default_tax_category", "is_active"]


class SubAccountForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = SubAccount
        fields = ["code", "name"]


class LockForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Company
        fields = ["books_locked_through"]
        widgets = {"books_locked_through": DateInput()}
