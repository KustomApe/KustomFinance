import datetime

from django import forms

from apps.core.forms import DateInput, StyledFormMixin
from apps.ledger.models import Account, Section

from .models import FixedAsset

SMALL_ASSET_LIMIT = 300_000
LUMP_SUM_LIMIT = 200_000


class AssetForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = FixedAsset
        fields = [
            "name",
            "account",
            "acquisition_date",
            "service_date",
            "acquisition_cost",
            "quantity",
            "method",
            "useful_life",
            "department",
            "location",
            "opening_date",
            "opening_accumulated",
            "notes",
        ]
        widgets = {
            "acquisition_date": DateInput(),
            "service_date": DateInput(),
            "opening_date": DateInput(),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["account"].queryset = Account.objects.filter(section=Section.FIXED_ASSETS, is_active=True)
        if self.instance.pk and self.instance.entries.exists():
            # 償却実績のある資産は計算の前提を変えない
            for name in [
                "acquisition_cost",
                "method",
                "useful_life",
                "service_date",
                "opening_date",
                "opening_accumulated",
                "account",
            ]:
                self.fields[name].disabled = True

    def clean(self):
        cleaned = super().clean()
        method, cost = cleaned.get("method"), cleaned.get("acquisition_cost") or 0
        if method in (FixedAsset.Method.STRAIGHT_LINE, FixedAsset.Method.DECLINING) and not cleaned.get(
            "useful_life"
        ):
            self.add_error("useful_life", "耐用年数を入力してください。")
        if method == FixedAsset.Method.IMMEDIATE and cost >= SMALL_ASSET_LIMIT:
            self.add_error("method", "少額減価償却資産は取得価額30万円未満の資産が対象です。")
        if method == FixedAsset.Method.LUMP_SUM and cost >= LUMP_SUM_LIMIT:
            self.add_error("method", "一括償却資産は取得価額20万円未満の資産が対象です。")
        if (
            cleaned.get("service_date")
            and cleaned.get("acquisition_date")
            and cleaned["service_date"] < cleaned["acquisition_date"]
        ):
            self.add_error("service_date", "事業供用日は取得日以降にしてください。")
        if (cleaned.get("opening_accumulated") or 0) and not cleaned.get("opening_date"):
            self.add_error("opening_date", "移行時の償却累計額を入力した場合は基準日を入力してください。")
        if (cleaned.get("opening_accumulated") or 0) >= cost > 0:
            self.add_error("opening_accumulated", "償却累計額は取得価額未満にしてください。")
        return cleaned


class RunForm(StyledFormMixin, forms.Form):
    through = forms.DateField(label="計上する月末日", widget=DateInput())

    def clean_through(self):
        from .services import month_end

        return month_end(self.cleaned_data["through"])


class DisposeForm(StyledFormMixin, forms.Form):
    date = forms.DateField(label="除却日", widget=DateInput(), initial=datetime.date.today)
    reason = forms.CharField(label="理由", max_length=200)
