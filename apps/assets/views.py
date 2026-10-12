import datetime

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts import roles
from apps.accounts.permissions import require_capability
from apps.core.exports import csv_response
from apps.core.numbering import next_number

from . import services
from .forms import AssetForm, DisposeForm, RunForm
from .models import DepreciationRate, FixedAsset


@require_capability(roles.VIEW)
def asset_list(request):
    assets = FixedAsset.objects.select_related("account", "department")
    status = request.GET.get("status", FixedAsset.Status.ACTIVE)
    if status:
        assets = assets.filter(status=status)
    rows = list(assets)
    if request.GET.get("format") == "csv":
        return csv_response(
            "固定資産台帳.csv",
            [
                "資産番号",
                "資産名",
                "勘定科目",
                "取得日",
                "事業供用日",
                "取得価額",
                "償却方法",
                "耐用年数",
                "償却累計額",
                "帳簿価額",
                "部門",
                "設置場所",
                "状態",
            ],
            [
                [
                    a.number,
                    a.name,
                    a.account.name,
                    a.acquisition_date,
                    a.service_date,
                    a.acquisition_cost,
                    a.get_method_display(),
                    a.useful_life or "",
                    a.acquisition_cost - a.book_value,
                    a.book_value,
                    a.department or "",
                    a.location,
                    a.get_status_display(),
                ]
                for a in rows
            ],
        )
    return render(
        request,
        "assets/list.html",
        {
            "assets": rows,
            "status": status,
            "statuses": FixedAsset.Status.choices,
            "total_cost": sum(a.acquisition_cost for a in rows),
            "total_book": sum(a.book_value for a in rows),
        },
    )


@require_capability(roles.LEDGER_EDIT)
def asset_edit(request, pk=None):
    asset = get_object_or_404(FixedAsset, pk=pk) if pk else None
    form = AssetForm(request.POST or None, instance=asset)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        if not obj.number:
            obj.number = next_number("asset", obj.acquisition_date)
        obj.save()
        messages.success(request, f"固定資産 {obj.number} を保存しました。")
        return redirect("assets:detail", obj.pk)
    return render(request, "assets/form.html", {"form": form, "object": asset})


@require_capability(roles.VIEW)
def asset_detail(request, pk):
    asset = get_object_or_404(FixedAsset.objects.select_related("account", "department"), pk=pk)
    form = DisposeForm(request.POST or None)
    if request.method == "POST" and request.user.can(roles.LEDGER_EDIT) and form.is_valid():
        try:
            services.dispose(asset, form.cleaned_data["date"], form.cleaned_data["reason"], request.user)
        except ValidationError as e:
            for m in e.messages:
                messages.error(request, m)
        else:
            messages.success(request, "除却しました。")
        return redirect("assets:detail", pk)
    try:
        schedule = services.projected_schedule(asset)
    except ValidationError as e:
        schedule, messages_ = [], e.messages
        for m in messages_:
            messages.warning(request, m)
    return render(
        request,
        "assets/detail.html",
        {
            "asset": asset,
            "schedule": schedule,
            "entries": asset.entries.select_related("journal"),
            "dispose_form": form,
        },
    )


@require_capability(roles.LEDGER_EDIT)
def run(request):
    today = datetime.date.today()
    form = RunForm(request.POST or request.GET or None, initial={"through": services.month_end(today)})
    rows, through = [], None
    if form.is_bound and form.is_valid():
        through = form.cleaned_data["through"]
        try:
            if request.method == "POST":
                journal = services.run_depreciation(through, request.user)
                if journal:
                    messages.success(request, f"減価償却費を計上しました（仕訳 {journal.number}）。")
                else:
                    messages.info(request, "計上する償却額はありません。")
                return redirect(f"{request.path}?through={through.isoformat()}")
            rows = services.preview(through)
        except ValidationError as e:
            for m in e.messages:
                messages.error(request, m)
    return render(
        request,
        "assets/run.html",
        {
            "form": form,
            "rows": rows,
            "through": through,
            "total": sum(r.amount for r in rows),
        },
    )


@require_capability(roles.VIEW)
def rate_list(request):
    return render(request, "assets/rates.html", {"rates": DepreciationRate.objects.all()})
