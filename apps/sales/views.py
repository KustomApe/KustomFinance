import datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.accounts import roles
from apps.accounts.permissions import require_capability
from apps.core.exports import csv_response
from apps.ledger.models import Account
from apps.masters.doc_services import copy_document
from apps.masters.doc_views import DocType
from apps.masters.documents import DocStatus
from apps.masters.models import Partner

from .forms import DeliveryForm, EstimateForm, InvoiceForm, ReceiptForm, SalesOrderForm
from .models import Delivery, Estimate, Invoice, Receipt, SalesOrder
from .services import cancel_invoice, cancel_receipt, create_receipt, invoice_from_deliveries, post_invoice


def _action(label, url, primary=False):
    return {"label": label, "url": url, "primary": primary}


def _estimate_actions(request, doc):
    if doc.status == DocStatus.ISSUED and request.user.can(roles.SALES_EDIT):
        return [_action("受注に変換", reverse("sales:estimate_to_order", args=[doc.pk]), True)]
    return []


def _order_actions(request, doc):
    if doc.status == DocStatus.ISSUED and request.user.can(roles.SALES_EDIT):
        return [
            _action("納品書を作成", reverse("sales:order_to_delivery", args=[doc.pk])),
            _action("請求書を作成", reverse("sales:order_to_invoice", args=[doc.pk]), True),
        ]
    return []


def _delivery_actions(request, doc):
    if doc.status == DocStatus.ISSUED and not doc.invoice_id and request.user.can(roles.SALES_EDIT):
        return [_action("請求書を作成", reverse("sales:delivery_to_invoice", args=[doc.pk]), True)]
    return []


def _links(*pairs):
    return [(label, docs) for label, docs in pairs if docs]


ESTIMATE = DocType(
    "estimate",
    "sales",
    Estimate,
    EstimateForm,
    "pdf/estimate.html",
    detail_fields=["valid_until", "delivery_terms"],
    extra_actions=_estimate_actions,
    related=lambda d: _links(("受注", list(d.orders.all()))),
)
ORDER = DocType(
    "order",
    "sales",
    SalesOrder,
    SalesOrderForm,
    "pdf/sales_order.html",
    detail_fields=["customer_order_number", "delivery_date"],
    extra_actions=_order_actions,
    related=lambda d: _links(
        ("見積書", [d.estimate] if d.estimate else []),
        ("納品書", list(d.deliveries.all())),
        ("請求書", list(d.invoices.all())),
    ),
)
DELIVERY = DocType(
    "delivery",
    "sales",
    Delivery,
    DeliveryForm,
    "pdf/delivery.html",
    extra_actions=_delivery_actions,
    related=lambda d: _links(
        ("受注", [d.order] if d.order else []), ("請求書", [d.invoice] if d.invoice else [])
    ),
)
INVOICE = DocType(
    "invoice",
    "sales",
    Invoice,
    InvoiceForm,
    "pdf/invoice.html",
    detail_fields=["sales_date", "due_date"],
    on_issue=post_invoice,
    on_cancel=cancel_invoice,
    cancel_capability=roles.LEDGER_EDIT,
    related=lambda d: _links(("受注", [d.order] if d.order else []), ("納品書", list(d.deliveries.all()))),
)


def _convert(request, source, target_model, target_spec, **fields):
    doc = copy_document(source, target_model, user=request.user, issue_date=datetime.date.today(), **fields)
    messages.success(request, f"{target_model.title}の下書きを作成しました。内容を確認して発行してください。")
    return redirect(target_spec.url("edit", doc.pk))


@require_POST
@require_capability(roles.SALES_EDIT)
def estimate_to_order(request, pk):
    estimate = get_object_or_404(Estimate, pk=pk, status=DocStatus.ISSUED)
    return _convert(request, estimate, SalesOrder, ORDER, estimate=estimate)


@require_POST
@require_capability(roles.SALES_EDIT)
def order_to_delivery(request, pk):
    order = get_object_or_404(SalesOrder, pk=pk, status=DocStatus.ISSUED)
    return _convert(request, order, Delivery, DELIVERY, order=order)


@require_POST
@require_capability(roles.SALES_EDIT)
def order_to_invoice(request, pk):
    order = get_object_or_404(SalesOrder, pk=pk, status=DocStatus.ISSUED)
    return _convert(request, order, Invoice, INVOICE, order=order)


@require_POST
@require_capability(roles.SALES_EDIT)
def deliveries_to_invoice(request, pk=None):
    ids = [pk] if pk else request.POST.getlist("delivery")
    deliveries = list(Delivery.objects.filter(pk__in=ids))
    try:
        invoice = invoice_from_deliveries(deliveries, request.user, datetime.date.today())
    except ValidationError as e:
        for m in e.messages:
            messages.error(request, m)
        return redirect("sales:billing")
    messages.success(request, "請求書の下書きを作成しました。内容を確認して発行してください。")
    return redirect(INVOICE.url("edit", invoice.pk))


@require_capability(roles.VIEW)
def billing(request):
    """締め請求: 未請求の納品書を取引先・期間で絞り込み、まとめて請求書を作成する。"""
    deliveries = Delivery.objects.filter(status=DocStatus.ISSUED, invoice__isnull=True).select_related(
        "partner"
    )
    if partner := request.GET.get("partner"):
        deliveries = deliveries.filter(partner_id=partner)
    if date_to := request.GET.get("date_to"):
        deliveries = deliveries.filter(issue_date__lte=date_to)
    return render(
        request,
        "sales/billing.html",
        {
            "deliveries": deliveries.order_by("partner__code", "issue_date"),
            "partners": Partner.objects.filter(is_customer=True, is_active=True),
        },
    )


@require_capability(roles.VIEW)
def receipt_list(request):
    receipts = Receipt.objects.select_related("partner", "deposit_account")
    if partner := request.GET.get("partner"):
        receipts = receipts.filter(partner_id=partner)
    if q := request.GET.get("q", "").strip():
        receipts = receipts.filter(
            Q(number__icontains=q) | Q(partner__name__icontains=q) | Q(memo__icontains=q)
        )
    page = Paginator(receipts, 30).get_page(request.GET.get("page"))
    return render(
        request,
        "sales/receipt_list.html",
        {
            "page": page,
            "partners": Partner.objects.filter(is_customer=True),
        },
    )


def _open_invoices(partner):
    invoices = Invoice.objects.filter(partner=partner, status=DocStatus.ISSUED).order_by(
        "due_date", "issue_date"
    )
    return [inv for inv in invoices if inv.outstanding > 0]


@require_capability(roles.LEDGER_EDIT)
def receipt_create(request):
    partner = Partner.objects.filter(
        pk=request.GET.get("partner") or request.POST.get("partner") or 0
    ).first()
    form = ReceiptForm(
        request.POST or None,
        initial={"date": datetime.date.today(), "deposit_account": Account.by_key("bank")},
    )
    invoices = _open_invoices(partner) if partner else []
    for inv in invoices:
        inv.posted_alloc = request.POST.get(f"alloc-{inv.pk}", "")
    if request.method == "POST" and partner and form.is_valid():
        allocations = []
        errors = []
        for inv in invoices:
            raw = request.POST.get(f"alloc-{inv.pk}", "").replace(",", "").strip()
            try:
                allocations.append((inv, Decimal(raw or 0)))
            except InvalidOperation:
                errors.append(f"請求書 {inv.number} の消込額が不正です。")
        if not errors:
            try:
                receipt = create_receipt(
                    partner=partner, allocations=allocations, user=request.user, **form.cleaned_data
                )
            except ValidationError as e:
                errors.extend(e.messages)
            else:
                messages.success(request, f"入金 {receipt.number} を登録しました。")
                return redirect("sales:receipt_detail", receipt.pk)
        for m in errors:
            messages.error(request, m)
    return render(
        request,
        "sales/receipt_form.html",
        {
            "form": form,
            "partner": partner,
            "invoices": invoices,
            "partners": Partner.objects.filter(is_customer=True, is_active=True),
        },
    )


@require_capability(roles.VIEW)
def receipt_detail(request, pk):
    receipt = get_object_or_404(
        Receipt.objects.select_related("partner", "deposit_account", "journal"), pk=pk
    )
    if request.method == "POST":
        if not request.user.can(roles.LEDGER_EDIT):
            messages.error(request, "権限がありません。")
        else:
            try:
                cancel_receipt(receipt, request.POST.get("reason", ""), request.user)
            except ValidationError as e:
                for m in e.messages:
                    messages.error(request, m)
            else:
                messages.success(request, "入金を取り消しました。")
        return redirect("sales:receipt_detail", pk)
    return render(
        request,
        "sales/receipt_detail.html",
        {
            "receipt": receipt,
            "allocations": receipt.allocations.select_related("invoice"),
        },
    )


AGING_BUCKETS = [
    ("期日内", None, 0),
    ("1〜30日", 1, 30),
    ("31〜60日", 31, 60),
    ("61〜90日", 61, 90),
    ("91日以上", 91, None),
]


@require_capability(roles.VIEW)
def receivables(request):
    """売掛金残高・年齢表（支払期日からの経過日数）。"""
    as_of = datetime.date.today()
    if raw := request.GET.get("as_of"):
        as_of = datetime.date.fromisoformat(raw)
    rows: dict[int, dict] = {}
    for inv in Invoice.objects.filter(status=DocStatus.ISSUED, issue_date__lte=as_of).select_related(
        "partner"
    ):
        outstanding = inv.outstanding
        if outstanding <= 0:
            continue
        overdue = (as_of - (inv.due_date or inv.issue_date)).days
        idx = next(
            i
            for i, (_, lo, hi) in enumerate(AGING_BUCKETS)
            if (lo is None or overdue >= lo) and (hi is None or overdue <= hi)
        )
        row = rows.setdefault(
            inv.partner_id,
            {
                "partner": inv.partner,
                "buckets": [Decimal(0)] * len(AGING_BUCKETS),
                "total": Decimal(0),
                "invoices": [],
            },
        )
        row["buckets"][idx] += outstanding
        row["total"] += outstanding
        row["invoices"].append((inv, outstanding, overdue))
    rows_list = sorted(rows.values(), key=lambda r: r["partner"].code)
    totals = [sum(r["buckets"][i] for r in rows_list) for i in range(len(AGING_BUCKETS))]
    if request.GET.get("format") == "csv":
        return csv_response(
            f"売掛金年齢表_{as_of}.csv",
            ["取引先コード", "取引先", *[b[0] for b in AGING_BUCKETS], "合計"],
            [[r["partner"].code, r["partner"].name, *r["buckets"], r["total"]] for r in rows_list],
        )
    return render(
        request,
        "sales/receivables.html",
        {
            "rows": rows_list,
            "buckets": [b[0] for b in AGING_BUCKETS],
            "totals": totals,
            "grand_total": sum(totals),
            "as_of": as_of,
        },
    )
