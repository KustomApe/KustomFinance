from django import forms

from apps.core.forms import DateInput, StyledFormMixin

from .models import Document
from .search import KIND_CHOICES


class DocumentForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Document
        fields = ["kind", "source", "transaction_date", "amount", "partner", "partner_name", "title", "file"]
        widgets = {
            "transaction_date": DateInput(),
            "file": forms.ClearableFileInput(attrs={"accept": "image/*,video/*,.heic,.heif,.pdf"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["file"].disabled = True
            self.fields["file"].required = False

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("partner") and not cleaned.get("partner_name"):
            self.add_error("partner_name", "取引先を選択するか、取引先名を入力してください。")
        return cleaned


class SearchForm(StyledFormMixin, forms.Form):
    date_from = forms.DateField(label="取引年月日（から）", required=False, widget=DateInput())
    date_to = forms.DateField(label="取引年月日（まで）", required=False, widget=DateInput())
    amount_min = forms.DecimalField(label="金額（以上）", required=False, decimal_places=0)
    amount_max = forms.DecimalField(label="金額（以下）", required=False, decimal_places=0)
    partner = forms.CharField(label="取引先", required=False)
    kind = forms.ChoiceField(label="書類", required=False, choices=[("", "すべて"), *KIND_CHOICES])
