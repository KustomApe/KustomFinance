from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts import roles
from apps.accounts.permissions import require_capability

from .forms import CompanyForm, FiscalYearForm
from .models import Company, FiscalYear


def dashboard(request):
    return render(
        request,
        "core/dashboard.html",
        {
            "fiscal_year": FiscalYear.objects.filter(is_closed=False).order_by("start_date").first(),
        },
    )


@require_capability(roles.SETTINGS)
def company_edit(request):
    company = Company.load()
    form = CompanyForm(request.POST or None, request.FILES or None, instance=company)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "自社情報を保存しました。")
        return redirect("core:company")
    return render(request, "core/company_form.html", {"form": form})


@require_capability(roles.VIEW)
def fiscal_year_list(request):
    return render(request, "core/fiscal_year_list.html", {"fiscal_years": FiscalYear.objects.all()})


@require_capability(roles.PERIOD_CLOSE)
def fiscal_year_edit(request, pk=None):
    instance = get_object_or_404(FiscalYear, pk=pk) if pk else None
    if instance and instance.is_closed:
        messages.error(request, "締め済みの会計期間は編集できません。")
        return redirect("core:fiscal_years")
    form = FiscalYearForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "会計期間を保存しました。")
        return redirect("core:fiscal_years")
    return render(request, "core/fiscal_year_form.html", {"form": form, "object": instance})
