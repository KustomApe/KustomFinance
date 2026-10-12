from django import forms

from apps.core.forms import StyledFormMixin

from .models import Department, Item, Partner, Project


class PartnerForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Partner
        fields = [
            "code",
            "name",
            "name_kana",
            "honorific",
            "is_customer",
            "is_supplier",
            "invoice_registration_number",
            "postal_code",
            "address",
            "phone",
            "email",
            "contact_person",
            "closing_day",
            "payment_month_offset",
            "payment_day",
            "bank_account_info",
            "notes",
            "is_active",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
            "bank_account_info": forms.Textarea(attrs={"rows": 2}),
        }

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("is_customer") and not cleaned.get("is_supplier"):
            raise forms.ValidationError("得意先・仕入先の少なくとも一方を選択してください。")
        if (cleaned.get("closing_day") or 0) > 28 or (cleaned.get("payment_day") or 0) > 28:
            raise forms.ValidationError("締日・支払日は 0（月末）または 1〜28 で入力してください。")
        return cleaned


class ItemForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Item
        fields = [
            "code",
            "name",
            "unit",
            "unit_price",
            "purchase_price",
            "tax_rate",
            "sales_account",
            "purchase_account",
            "is_active",
        ]


class DepartmentForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Department
        fields = ["code", "name", "is_active"]


class ProjectForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Project
        fields = ["code", "name", "partner", "is_active"]
