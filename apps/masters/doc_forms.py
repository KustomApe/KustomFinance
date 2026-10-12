from django import forms

from .models import Item, TaxRate


class LineForm(forms.Form):
    item = forms.ModelChoiceField(Item.objects.all(), required=False)
    transaction_date = forms.DateField(required=False)
    description = forms.CharField(max_length=255, required=False)
    quantity = forms.DecimalField(max_digits=12, decimal_places=3, required=False)
    unit = forms.CharField(max_length=10, required=False)
    unit_price = forms.DecimalField(max_digits=15, decimal_places=2, required=False)
    tax_rate = forms.ChoiceField(choices=TaxRate.choices, initial=TaxRate.STANDARD)

    def is_blank(self) -> bool:
        d = self.cleaned_data
        return not (d.get("item") or d.get("description") or d.get("unit_price"))

    def clean(self):
        cleaned = super().clean()
        if not self.is_blank():
            if not cleaned.get("description"):
                if cleaned.get("item"):
                    cleaned["description"] = cleaned["item"].name
                else:
                    raise forms.ValidationError("品名・内容を入力してください。")
            if cleaned.get("quantity") is None:
                cleaned["quantity"] = 1
            if cleaned.get("unit_price") is None:
                cleaned["unit_price"] = 0
        return cleaned


LineFormSet = forms.formset_factory(LineForm, extra=0, min_num=0)
