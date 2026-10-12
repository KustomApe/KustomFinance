import datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.accounts import roles
from apps.accounts.permissions import require_capability
from apps.core.exports import csv_response
from apps.ledger.models import Account
from apps.masters.advance_views import AdvanceScreens
from apps.masters.advances import PURCHASE
from apps.masters.doc_services import copy_document
from apps.masters.doc_views import DocType, aging_view
from apps.masters.documents import DocStatus
from apps.masters.models import Partner

from .forms import BillForm, GoodsReceiptForm, PaymentForm, PurchaseOrderForm
from .models import Bill, GoodsReceipt, Payment, PaymentAllocation, PurchaseOrder
from .services import bill_from_receipts, cancel_bill, cancel_payment, create_payment, post_bill

SUPPLIERS = {"is_supplier": True}


def _action(label, url, primary=False, get=False):
    return {"label": label, "url": url, "primary": primary, "get": get}


def _links(*pairs):
    return [(label, docs) for label, docs in pairs if docs]


def _order_actions(request, doc):
    if doc.status == DocStatus.ISSUED and request.user.can(roles.SALES_EDIT):
        return [
            _action("検収を登録", reverse("purchasing:order_to_receipt", args=[doc.pk])),
            _action("仕入請求書を登録", reverse("purchasing:order_to_bill", args=[doc.pk]), True),
        ]
    return []


def _receipt_actions(request, doc):
    if doc.status == DocStatus.ISSUED and not doc.bill_id and request.user.can(roles.SALES_EDIT):
        return [_action("仕入請求書を作成", reverse("purchasing:receipt_to_bill", args=[doc.pk]), True)]
    return []


def _bill_actions(request, doc):
    if doc.attachment:
        return [
            _action("受領した請求書を表示", reverse("purchasing:bill_attachment", args=[doc.pk]), get=True)
        ]
    return []


ADVANCES = AdvanceScreens(
    PURCHASE,
    source_model=Payment,
    document_model=Bill,
    allocation_model=PaymentAllocation,
    namespace="purchasing",
    document_key="bill",
    source_detail="purchasing:payment_detail",
    source_label="支払",
)

ORDER = DocType(
    "order",
    "purchasing",
    PurchaseOrder,
    PurchaseOrderForm,
    "pdf/purchase_order.html",
    partner_filter=SUPPLIERS,
    price_field="purchase_price",
    detail_fields=["delivery_date", "delivery_place", "payment_terms"],
    extra_actions=_order_actions,
    related=lambda d: _links(("検収", list(d.receipts.all())), ("仕入請求書", list(d.bills.all()))),
)
RECEIPT = DocType(
    "receipt",
    "purchasing",
    GoodsReceipt,
    GoodsReceiptForm,
    "pdf/goods_receipt.html",
    partner_filter=SUPPLIERS,
    price_field="purchase_price",
    extra_actions=_receipt_actions,
    issue_label="検収を確定",
    related=lambda d: _links(
        ("注文書", [d.order] if d.order else []), ("仕入請求書", [d.bill] if d.bill else [])
    ),
)
BILL = DocType(
    "bill",
    "purchasing",
    Bill,
    BillForm,
    "pdf/bill.html",
    partner_filter=SUPPLIERS,
    price_field="purchase_price",
    detail_fields=[
        "supplier_invoice_number",
        "supplier_registration_number",
        "purchase_date",
        "due_date",
        "account",
        "attachment_sha256",
    ],
    on_issue=post_bill,
    on_cancel=cancel_bill,
    cancel_capability=roles.LEDGER_EDIT,
    issue_label="計上する",
    issue_note="仕入仕訳（買掛金）が計上されます",
    extra_actions=_bill_actions,
    related=lambda d: _links(
        ("注文書", [d.order] if d.order else []), ("検収", list(d.goods_receipts.all()))
    ),
    allocations=ADVANCES.allocations,
    panel=ADVANCES.panel,
)


def _convert(request, source, target_model, target_spec, **fields):
    doc = copy_document(source, target_model, user=request.user, issue_date=datetime.date.today(), **fields)
    messages.success(request, f"{target_model.title}の下書きを作成しました。内容を確認して確定してください。")
    return redirect(target_spec.url("edit", doc.pk))


@require_POST
@require_capability(roles.SALES_EDIT)
def order_to_receipt(request, pk):
    order = get_object_or_404(PurchaseOrder, pk=pk, status=DocStatus.ISSUED)
    return _convert(request, order, GoodsReceipt, RECEIPT, order=order)


@require_POST
@require_capability(roles.SALES_EDIT)
def order_to_bill(request, pk):
    order = get_object_or_404(PurchaseOrder, pk=pk, status=DocStatus.ISSUED)
    return _convert(request, order, Bill, BILL, order=order)


@require_POST
@require_capability(roles.SALES_EDIT)
def receipts_to_bill(request, pk=None):
    ids = [pk] if pk else request.POST.getlist("receipt")
    try:
        bill = bill_from_receipts(
            list(GoodsReceipt.objects.filter(pk__in=ids)), request.user, datetime.date.today()
        )
    except ValidationError as e:
        for m in e.messages:
            messages.error(request, m)
        return redirect("purchasing:unbilled")
    messages.success(
        request, "仕入請求書の下書きを作成しました。請求書の内容（税額など）と照合して計上してください。"
    )
    return redirect(BILL.url("edit", bill.pk))


@require_capability(roles.VIEW)
def bill_attachment(request, pk):
    bill = get_object_or_404(Bill, pk=pk)
    if not bill.attachment:
        raise Http404
    return FileResponse(bill.attachment.open("rb"), filename=bill.attachment.name.rsplit("/", 1)[-1])


@require_capability(roles.VIEW)
def unbilled(request):
    """請求未計上の検収を仕入先ごとにまとめて仕入請求書にする。"""
    receipts = GoodsReceipt.objects.filter(status=DocStatus.ISSUED, bill__isnull=True).select_related(
        "partner"
    )
    if partner := request.GET.get("partner"):
        receipts = receipts.filter(partner_id=partner)
    if date_to := request.GET.get("date_to"):
        receipts = receipts.filter(issue_date__lte=date_to)
    return render(
        request,
        "purchasing/unbilled.html",
        {
            "receipts": receipts.order_by("partner__code", "issue_date"),
            "partners": Partner.objects.filter(is_supplier=True, is_active=True),
        },
    )


@require_capability(roles.VIEW)
def payment_list(request):
    payments = Payment.objects.select_related("partner", "pay_account")
    if partner := request.GET.get("partner"):
        payments = payments.filter(partner_id=partner)
    if q := request.GET.get("q", "").strip():
        payments = payments.filter(
            Q(number__icontains=q) | Q(partner__name__icontains=q) | Q(memo__icontains=q)
        )
    page = Paginator(payments, 30).get_page(request.GET.get("page"))
    return render(
        request,
        "purchasing/payment_list.html",
        {
            "page": page,
            "partners": Partner.objects.filter(is_supplier=True),
        },
    )


def _open_bills(partner):
    bills = Bill.objects.filter(partner=partner, status=DocStatus.ISSUED).order_by("due_date", "issue_date")
    return [b for b in bills if b.outstanding > 0]


@require_capability(roles.LEDGER_EDIT)
def payment_create(request):
    partner = Partner.objects.filter(
        pk=request.GET.get("partner") or request.POST.get("partner") or 0
    ).first()
    form = PaymentForm(
        request.POST or None, initial={"date": datetime.date.today(), "pay_account": Account.by_key("bank")}
    )
    bills = _open_bills(partner) if partner else []
    for bill in bills:
        bill.posted_alloc = request.POST.get(f"alloc-{bill.pk}", "")
    if request.method == "POST" and partner and form.is_valid():
        allocations, errors = [], []
        for bill in bills:
            raw = request.POST.get(f"alloc-{bill.pk}", "").replace(",", "").strip()
            try:
                allocations.append((bill, Decimal(raw or 0)))
            except InvalidOperation:
                errors.append(f"仕入請求書 {bill.number} の消込額が不正です。")
        if not errors:
            try:
                payment = create_payment(
                    partner=partner, allocations=allocations, user=request.user, **form.cleaned_data
                )
            except ValidationError as e:
                errors.extend(e.messages)
            else:
                messages.success(request, f"支払 {payment.number} を登録しました。")
                return redirect("purchasing:payment_detail", payment.pk)
        for m in errors:
            messages.error(request, m)
    return render(
        request,
        "purchasing/payment_form.html",
        {
            "form": form,
            "partner": partner,
            "bills": bills,
            "partners": Partner.objects.filter(is_supplier=True, is_active=True),
        },
    )


@require_capability(roles.VIEW)
def payment_detail(request, pk):
    payment = get_object_or_404(Payment.objects.select_related("partner", "pay_account", "journal"), pk=pk)
    if request.method == "POST":
        if not request.user.can(roles.LEDGER_EDIT):
            messages.error(request, "権限がありません。")
        else:
            try:
                cancel_payment(payment, request.POST.get("reason", ""), request.user)
            except ValidationError as e:
                for m in e.messages:
                    messages.error(request, m)
            else:
                messages.success(request, "支払を取り消しました。")
        return redirect("purchasing:payment_detail", pk)
    return render(
        request,
        "purchasing/payment_detail.html",
        {
            "payment": payment,
            "allocations": payment.allocations.select_related("bill"),
        },
    )


@require_capability(roles.VIEW)
def payables(request):
    return aging_view(
        request,
        Bill.objects.filter(status=DocStatus.ISSUED),
        title="買掛金残高・年齢表",
        detail_url="purchasing:bill_detail",
        doc_label="仕入請求書",
    )


@require_capability(roles.VIEW)
def schedule(request):
    """支払予定表: 未払の仕入請求書を支払期日順に表示する。"""
    date_to = request.GET.get("date_to")
    bills = (
        Bill.objects.filter(status=DocStatus.ISSUED)
        .select_related("partner")
        .order_by("due_date", "partner__code")
    )
    if date_to:
        bills = bills.filter(due_date__lte=date_to)
    groups: dict = {}
    for bill in bills:
        outstanding = bill.outstanding
        if outstanding <= 0:
            continue
        g = groups.setdefault(bill.due_date, {"date": bill.due_date, "bills": [], "total": Decimal(0)})
        g["bills"].append((bill, outstanding))
        g["total"] += outstanding
    groups_list = list(groups.values())
    if request.GET.get("format") == "csv":
        return csv_response(
            "支払予定表.csv",
            ["支払期日", "仕入先", "仕入請求書", "先方請求書番号", "未払額", "振込先"],
            [
                [
                    g["date"],
                    b.partner.name,
                    b.number,
                    b.supplier_invoice_number,
                    amount,
                    b.partner.bank_account_info,
                ]
                for g in groups_list
                for b, amount in g["bills"]
            ],
        )
    return render(
        request,
        "purchasing/schedule.html",
        {
            "groups": groups_list,
            "grand_total": sum((g["total"] for g in groups_list), Decimal(0)),
            "today": datetime.date.today(),
        },
    )
