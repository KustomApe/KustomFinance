import datetime

from django.shortcuts import render

from apps.accounts import roles
from apps.accounts.permissions import require_capability
from apps.core.exports import table_response
from apps.ledger.selectors import fiscal_year_start
from apps.masters.models import Department

from .selectors import balance_sheet, profit_and_loss, tax_summary


def _date(value, default):
    try:
        return datetime.date.fromisoformat(value) if value else default
    except ValueError:
        return default


@require_capability(roles.VIEW)
def pl_view(request):
    today = datetime.date.today()
    date_from = _date(request.GET.get("date_from"), fiscal_year_start(today))
    date_to = _date(request.GET.get("date_to"), today)
    department = Department.objects.filter(pk=request.GET.get("department") or 0).first()
    compare = bool(request.GET.get("compare"))
    lines = profit_and_loss(date_from, date_to, department, compare)
    if fmt := request.GET.get("format"):
        header = ["項目", "金額"] + (["前年同期"] if compare else [])
        rows = [
            [("　" * ln.level) + ln.label, ln.amount if ln.level or ln.bold and ln.amount else ""]
            + ([ln.compare if ln.compare is not None else ""] if compare else [])
            for ln in lines
        ]
        return table_response(fmt, f"損益計算書_{date_from}_{date_to}", header, rows)
    return render(
        request,
        "reports/pl.html",
        {
            "lines": lines,
            "date_from": date_from,
            "date_to": date_to,
            "compare": compare,
            "departments": Department.objects.filter(is_active=True),
            "department": department,
        },
    )


@require_capability(roles.VIEW)
def bs_view(request):
    as_of = _date(request.GET.get("as_of"), datetime.date.today())
    bs = balance_sheet(as_of)
    if fmt := request.GET.get("format"):
        rows = [["【資産】", ""]] + [
            [("　" * ln.level) + ln.label, ln.amount if ln.amount or ln.level == 2 else ""]
            for ln in bs.assets
        ]
        rows += [["【負債・純資産】", ""]] + [
            [("　" * ln.level) + ln.label, ln.amount if ln.amount or ln.level == 2 else ""]
            for ln in bs.liabilities
        ]
        return table_response(fmt, f"貸借対照表_{as_of}", ["項目", "金額"], rows)
    return render(
        request,
        "reports/bs.html",
        {"bs": bs, "as_of": as_of, "balanced": bs.total_assets == bs.total_liabilities_equity},
    )


@require_capability(roles.VIEW)
def tax_view(request):
    today = datetime.date.today()
    date_from = _date(request.GET.get("date_from"), fiscal_year_start(today))
    date_to = _date(request.GET.get("date_to"), today)
    summary = tax_summary(date_from, date_to)
    if fmt := request.GET.get("format"):
        rows = [[r.category.name, "売上", r.base, r.tax, r.gross] for r in summary.sales]
        rows += [[r.category.name, "仕入", r.base, r.tax, r.gross] for r in summary.purchases]
        return table_response(
            fmt,
            f"消費税集計表_{date_from}_{date_to}",
            ["税区分", "区分", "税抜金額", "消費税額", "税込金額"],
            rows,
        )
    return render(request, "reports/tax.html", {"s": summary, "date_from": date_from, "date_to": date_to})
