from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts import roles
from apps.accounts.permissions import require_capability

from .forms import CompanyForm, FiscalYearForm
from .models import Company, FiscalYear


def dashboard(request):
    import datetime

    from apps.banking.models import BankTransaction
    from apps.expenses.models import ExpenseClaim
    from apps.ledger.models import Account, AccountType, Section
    from apps.ledger.selectors import fiscal_year_start, trial_balance
    from apps.masters.documents import DocStatus
    from apps.reports.selectors import _pl_amounts
    from apps.sales.models import Invoice

    today = datetime.date.today()
    fy_start = fiscal_year_start(today)
    tb = {r.account.system_key or r.account.pk: r.closing for r in trial_balance(fy_start, today).rows}
    sections = {a.pk: (a.section, a.account_type) for a in Account.objects.all()}

    def pl(date_from, date_to):
        amounts = _pl_amounts(date_from, date_to)
        sales = sum(v for k, v in amounts.items() if sections[k][0] == Section.SALES)
        revenue = sum(v for k, v in amounts.items() if sections[k][1] == AccountType.REVENUE)
        expense = sum(v for k, v in amounts.items() if sections[k][1] == AccountType.EXPENSE)
        return sales, revenue - expense

    months = []
    first = today.replace(day=1)
    for i in range(11, -1, -1):
        y, m = divmod(first.year * 12 + first.month - 1 - i, 12)
        start = datetime.date(y, m + 1, 1)
        end = datetime.date(y + (m + 1) // 12, (m + 1) % 12 + 1, 1) - datetime.timedelta(days=1)
        sales, profit = pl(start, end)
        months.append({"month": start, "sales": sales, "profit": profit})
    max_sales = max((m["sales"] for m in months), default=0) or 1
    for m in months:
        m["ratio"] = int(m["sales"] / max_sales * 100) if m["sales"] > 0 else 0
    overdue = [
        inv
        for inv in Invoice.objects.filter(status=DocStatus.ISSUED, due_date__lt=today)
        if inv.outstanding > 0
    ]
    return render(
        request,
        "core/dashboard.html",
        {
            "fiscal_year": FiscalYear.objects.filter(is_closed=False).order_by("start_date").first(),
            "month_sales": months[-1]["sales"],
            "ytd_profit": pl(fy_start, today)[1],
            "cash": tb.get("cash", 0) + tb.get("bank", 0) + tb.get("petty_cash", 0),
            "receivable": tb.get("accounts_receivable", 0),
            "payable": tb.get("accounts_payable", 0),
            "overdue_count": len(overdue),
            "overdue_total": sum(inv.outstanding for inv in overdue),
            "pending_expenses": ExpenseClaim.objects.filter(status=ExpenseClaim.Status.SUBMITTED).count(),
            "unprocessed_bank": BankTransaction.objects.filter(
                status=BankTransaction.Status.UNPROCESSED
            ).count(),
            "months": months,
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
