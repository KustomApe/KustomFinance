from django import forms

from .models import Company, FiscalYear


class StyledFormMixin:
    """ウィジェットに共通のCSSクラスを付与する。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                css = "checkbox"
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                css = "select"
            elif isinstance(widget, forms.ClearableFileInput):
                css = "file-input"
            else:
                css = "input"
            widget.attrs["class"] = f"{css} {widget.attrs.get('class', '')}".strip()


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, attrs=None):
        super().__init__(attrs, format="%Y-%m-%d")


class CompanyForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Company
        fields = [
            "name",
            "representative",
            "postal_code",
            "address",
            "phone",
            "fax",
            "email",
            "corporate_number",
            "invoice_registration_number",
            "fiscal_year_start_month",
            "tax_rounding",
            "bank_account_info",
            "seal_image",
        ]
        widgets = {"bank_account_info": forms.Textarea(attrs={"rows": 3})}


class FiscalYearForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = FiscalYear
        fields = ["name", "start_date", "end_date"]
        widgets = {"start_date": DateInput(), "end_date": DateInput()}

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if start and end:
            overlap = FiscalYear.objects.filter(start_date__lte=end, end_date__gte=start)
            if self.instance.pk:
                overlap = overlap.exclude(pk=self.instance.pk)
            if overlap.exists():
                raise forms.ValidationError("他の会計期間と期間が重複しています。")
        return cleaned
