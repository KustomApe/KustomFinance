"""帳票（見積書・請求書・注文書など）の一覧・編集・発行・取消・PDFの共通ビュー。

各アプリは DocType を定義し、doc_urlpatterns() で URL を生成する。
"""

import datetime
from collections.abc import Callable
from dataclasses import dataclass, field

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.views.decorators.http import require_POST

from apps.accounts import roles
from apps.core.models import Company

from .doc_forms import LineFormSet
from .doc_services import (
    LINE_FIELDS,
    cancel_document,
    copy_document,
    document_pdf,
    issue_document,
    save_document,
)
from .documents import DocStatus
from .models import Item, Partner, TaxRate


@dataclass
class DocType:
    key: str
    namespace: str
    model: type
    form_class: type
    pdf_template: str
    partner_filter: dict = field(default_factory=lambda: {"is_customer": True})
    price_field: str = "unit_price"
    on_issue: Callable | None = None
    on_cancel: Callable | None = None
    cancel_capability: str = roles.SALES_EDIT
    detail_fields: list[str] = field(default_factory=list)
    extra_actions: Callable | None = None  # (request, doc) -> list[dict(label, url, method)]
    related: Callable | None = None  # (doc) -> list[(label, [docs])]

    @property
    def title(self) -> str:
        return self.model.title

    def url(self, action: str, *args) -> str:
        return reverse(f"{self.namespace}:{self.key}_{action}", args=args)


def _ctx(spec: DocType, **extra) -> dict:
    return {
        "spec": spec,
        "title": spec.title,
        "list_url": spec.url("list"),
        "new_url": spec.url("new"),
        **extra,
    }


def _options(spec: DocType) -> dict:
    return {
        "items": [
            {
                "id": i.pk,
                "label": f"{i.code} {i.name}",
                "name": i.name,
                "unit": i.unit,
                "price": str(getattr(i, spec.price_field)),
                "tax": i.tax_rate,
            }
            for i in Item.objects.filter(is_active=True)
        ],
        "taxRates": [{"id": v, "label": label} for v, label in TaxRate.choices],
        "taxPercent": {"10": 10, "8R": 8},
        "rounding": Company.load().tax_rounding,
    }


def _rows_from_post(data) -> list[dict]:
    total = min(int(data.get("lines-TOTAL_FORMS") or 0), 300)
    return [{f: data.get(f"lines-{i}-{f}", "") for f in LINE_FIELDS} for i in range(total)]


def _rows_from_doc(doc) -> list[dict]:
    return [
        {
            "item": str(ln.item_id or ""),
            "transaction_date": ln.transaction_date.isoformat() if ln.transaction_date else "",
            "description": ln.description,
            "quantity": str(ln.quantity.normalize()),
            "unit": ln.unit,
            "unit_price": str(ln.unit_price.normalize()),
            "tax_rate": ln.tax_rate,
        }
        for ln in doc.lines.all()
    ]


def _require(request, capability):
    if not request.user.can(capability):
        raise PermissionDenied


def list_view(spec: DocType):
    def view(request):
        _require(request, roles.VIEW)
        qs = spec.model.objects.select_related("partner")
        if status := request.GET.get("status"):
            qs = qs.filter(status=status)
        if partner := request.GET.get("partner"):
            qs = qs.filter(partner_id=partner)
        if q := request.GET.get("q", "").strip():
            qs = qs.filter(Q(number__icontains=q) | Q(subject__icontains=q) | Q(partner__name__icontains=q))
        if date_from := request.GET.get("date_from"):
            qs = qs.filter(issue_date__gte=date_from)
        if date_to := request.GET.get("date_to"):
            qs = qs.filter(issue_date__lte=date_to)
        page = Paginator(qs, 30).get_page(request.GET.get("page"))
        for doc in page:
            doc.url = spec.url("detail", doc.pk)
        return render(
            request,
            "documents/list.html",
            _ctx(
                spec,
                page=page,
                statuses=DocStatus.choices,
                partners=Partner.objects.filter(**spec.partner_filter, is_active=True),
            ),
        )

    return view


def edit_view(spec: DocType):
    def view(request, pk=None):
        _require(request, roles.SALES_EDIT)
        doc = get_object_or_404(spec.model, pk=pk) if pk else None
        if doc and not doc.is_draft:
            messages.error(request, "発行済みの帳票は編集できません。")
            return redirect(spec.url("detail", doc.pk))
        initial = {"issue_date": datetime.date.today()}
        form = spec.form_class(request.POST or None, instance=doc, initial=initial)
        form.fields["partner"].queryset = Partner.objects.filter(**spec.partner_filter, is_active=True)
        errors: list[str] = []
        rows = _rows_from_doc(doc) if doc else [{"quantity": "1", "tax_rate": TaxRate.STANDARD}]
        if request.method == "POST":
            rows = _rows_from_post(request.POST)
            formset = LineFormSet(request.POST, prefix="lines")
            if form.is_valid() and formset.is_valid():
                lines = [f.cleaned_data for f in formset.forms if not f.is_blank()]
                obj = form.save(commit=False)
                if not obj.pk:
                    obj.created_by = request.user
                try:
                    obj = save_document(obj, lines)
                except ValidationError as e:
                    errors.extend(e.messages)
                else:
                    messages.success(request, f"{spec.title}を保存しました。")
                    return redirect(spec.url("detail", obj.pk))
            else:
                for i, f in enumerate(formset.forms, 1):
                    errors.extend(f"明細{i}行目: {e}" for e in f.non_field_errors())
                    errors.extend(
                        f"明細{i}行目: {f.fields[k].label or k} {', '.join(v)}"
                        for k, v in f.errors.items()
                        if k != "__all__"
                    )
        return render(
            request,
            "documents/form.html",
            _ctx(
                spec,
                form=form,
                object=doc,
                errors=errors,
                rows=rows,
                options=_options(spec),
            ),
        )

    return view


def detail_view(spec: DocType):
    def view(request, pk):
        _require(request, roles.VIEW)
        doc = get_object_or_404(spec.model.objects.select_related("partner", "created_by"), pk=pk)
        fields = [(spec.model._meta.get_field(f).verbose_name, getattr(doc, f)) for f in spec.detail_fields]
        return render(
            request,
            "documents/detail.html",
            _ctx(
                spec,
                doc=doc,
                lines=doc.lines.select_related("item"),
                fields=fields,
                actions=spec.extra_actions(request, doc) if spec.extra_actions else [],
                related=spec.related(doc) if spec.related else [],
                urls={a: spec.url(a, doc.pk) for a in ("edit", "delete", "issue", "cancel", "pdf", "copy")},
                can_cancel=request.user.can(spec.cancel_capability),
            ),
        )

    return view


def delete_view(spec: DocType):
    @require_POST
    def view(request, pk):
        _require(request, roles.SALES_EDIT)
        doc = get_object_or_404(spec.model, pk=pk)
        if not doc.is_draft:
            messages.error(request, "発行済みの帳票は削除できません。取消を行ってください。")
            return redirect(spec.url("detail", pk))
        doc.delete()
        messages.success(request, "下書きを削除しました。")
        return redirect(spec.url("list"))

    return view


def issue_view(spec: DocType):
    @require_POST
    def view(request, pk):
        _require(request, roles.SALES_EDIT)
        doc = get_object_or_404(spec.model, pk=pk)
        try:
            doc = issue_document(doc, spec.pdf_template, user=request.user, on_issue=spec.on_issue)
        except ValidationError as e:
            for m in e.messages:
                messages.error(request, m)
        else:
            messages.success(request, f"{spec.title} {doc.number} を発行しました。")
        return redirect(spec.url("detail", pk))

    return view


def cancel_view(spec: DocType):
    @require_POST
    def view(request, pk):
        _require(request, spec.cancel_capability)
        doc = get_object_or_404(spec.model, pk=pk)
        try:
            cancel_document(doc, request.POST.get("reason", ""), user=request.user, on_cancel=spec.on_cancel)
        except ValidationError as e:
            for m in e.messages:
                messages.error(request, m)
        else:
            messages.success(request, f"{spec.title}を取り消しました。")
        return redirect(spec.url("detail", pk))

    return view


def pdf_view(spec: DocType):
    def view(request, pk):
        _require(request, roles.VIEW)
        doc = get_object_or_404(spec.model, pk=pk)
        filename = f"{doc.title}_{doc.number or 'draft'}.pdf"
        if doc.pdf_file:
            return FileResponse(doc.pdf_file.open("rb"), content_type="application/pdf", filename=filename)
        response = HttpResponse(document_pdf(doc, spec.pdf_template), content_type="application/pdf")
        response["Content-Disposition"] = "inline"
        return response

    return view


def copy_view(spec: DocType):
    @require_POST
    def view(request, pk):
        _require(request, roles.SALES_EDIT)
        source = get_object_or_404(spec.model, pk=pk)
        doc = copy_document(source, spec.model, user=request.user, issue_date=datetime.date.today())
        messages.success(request, f"{spec.title}を複製しました。")
        return redirect(spec.url("edit", doc.pk))

    return view


def doc_urlpatterns(spec: DocType, prefix: str) -> list:
    return [
        path(f"{prefix}/", list_view(spec), name=f"{spec.key}_list"),
        path(f"{prefix}/new/", edit_view(spec), name=f"{spec.key}_new"),
        path(f"{prefix}/<int:pk>/", detail_view(spec), name=f"{spec.key}_detail"),
        path(f"{prefix}/<int:pk>/edit/", edit_view(spec), name=f"{spec.key}_edit"),
        path(f"{prefix}/<int:pk>/delete/", delete_view(spec), name=f"{spec.key}_delete"),
        path(f"{prefix}/<int:pk>/issue/", issue_view(spec), name=f"{spec.key}_issue"),
        path(f"{prefix}/<int:pk>/cancel/", cancel_view(spec), name=f"{spec.key}_cancel"),
        path(f"{prefix}/<int:pk>/pdf/", pdf_view(spec), name=f"{spec.key}_pdf"),
        path(f"{prefix}/<int:pk>/copy/", copy_view(spec), name=f"{spec.key}_copy"),
    ]
