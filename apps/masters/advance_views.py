"""前受金・前渡金の充当に関する画面（販売・購買共通）。"""

import datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.views.decorators.http import require_POST

from apps.accounts import roles

from .advances import AdvanceKind, apply_advance, available_sources, cancel_application


class AdvanceScreens:
    def __init__(
        self,
        kind: AdvanceKind,
        *,
        source_model,
        document_model,
        allocation_model,
        namespace: str,
        document_key: str,
        source_detail: str,
        source_label: str,
    ):
        self.kind = kind
        self.source_model = source_model
        self.document_model = document_model
        self.allocation_model = allocation_model
        self.ns = namespace
        self.document_key = document_key
        self.source_detail = source_detail
        self.source_label = source_label  # 入金 / 支払

    # ---- 帳票詳細に表示する部品 ----

    def allocations(self, request, doc) -> list[dict]:
        rows = []
        for a in doc.allocations.select_related(self.kind.source_field).order_by("id"):
            source = getattr(a, self.kind.source_field)
            applied = a.is_advance_application
            rows.append(
                {
                    "label": f"{self.kind.advance_label}充当" if applied else f"{self.source_label}消込",
                    "number": source.number,
                    "date": a.applied_date or source.date,
                    "amount": a.amount,
                    "url": reverse(self.source_detail, args=[source.pk]),
                    "cancelled": source.status == "cancelled" or a.cancelled_at is not None,
                    "cancel_url": reverse(f"{self.ns}:advance_cancel", args=[a.pk])
                    if applied and not a.cancelled_at and request.user.can(roles.LEDGER_EDIT)
                    else "",
                }
            )
        return rows

    def panel(self, request, doc) -> dict | None:
        if doc.status != "issued" or doc.outstanding <= 0 or not request.user.can(roles.LEDGER_EDIT):
            return None
        sources = available_sources(self.kind, self.source_model, doc.partner)
        if not sources:
            return None
        return {
            "template": "documents/_advance_panel.html",
            "label": self.kind.advance_label,
            "source_label": self.source_label,
            "sources": sources,
            "outstanding": doc.outstanding,
            "action": reverse(f"{self.ns}:advance_apply", args=[doc.pk]),
            "today": datetime.date.today(),
        }

    # ---- ビュー ----

    def apply_view(self):
        @require_POST
        def view(request, pk):
            if not request.user.can(roles.LEDGER_EDIT):
                raise PermissionDenied
            doc = get_object_or_404(self.document_model, pk=pk)
            source = get_object_or_404(self.source_model, pk=request.POST.get("source"))
            try:
                amount = Decimal(request.POST.get("amount", "").replace(",", "") or 0)
                date = datetime.date.fromisoformat(request.POST.get("date", ""))
                apply_advance(self.kind, source, doc, amount, date, request.user)
            except (InvalidOperation, ValueError):
                messages.error(request, "充当額・充当日を正しく入力してください。")
            except ValidationError as e:
                for m in e.messages:
                    messages.error(request, m)
            else:
                messages.success(request, f"{self.kind.advance_label} {amount:,}円を充当しました。")
            return redirect(f"{self.ns}:{self.document_key}_detail", pk)

        return view

    def cancel_view(self):
        @require_POST
        def view(request, pk):
            if not request.user.can(roles.LEDGER_EDIT):
                raise PermissionDenied
            allocation = get_object_or_404(self.allocation_model, pk=pk)
            document = getattr(allocation, self.kind.document_field)
            try:
                cancel_application(self.kind, allocation, request.POST.get("reason", ""), request.user)
            except ValidationError as e:
                for m in e.messages:
                    messages.error(request, m)
            else:
                messages.success(request, f"{self.kind.advance_label}の充当を取り消しました。")
            return redirect(f"{self.ns}:{self.document_key}_detail", document.pk)

        return view

    def list_view(self):
        def view(request):
            if not request.user.can(roles.VIEW):
                raise PermissionDenied
            sources = [
                s
                for s in self.source_model.objects.filter(status="active")
                .select_related("partner")
                .prefetch_related("allocations")
                .order_by("partner__code", "date")
                if s.advance_amount > 0
            ]
            open_docs: dict[int, int] = {}
            for doc in self.document_model.objects.filter(
                status="issued", partner_id__in={s.partner_id for s in sources}
            ):
                if doc.outstanding > 0:
                    open_docs[doc.partner_id] = open_docs.get(doc.partner_id, 0) + 1
            for s in sources:
                s.open_documents = open_docs.get(s.partner_id, 0)
                s.detail_url = reverse(self.source_detail, args=[s.pk])
                s.documents_url = (
                    f"{reverse(f'{self.ns}:{self.document_key}_list')}?partner={s.partner_id}&status=issued"
                )
            return render(
                request,
                "documents/advances.html",
                {
                    "title": f"{self.kind.advance_label}残高",
                    "label": self.kind.advance_label,
                    "source_label": self.source_label,
                    "document_title": self.document_model.title,
                    "sources": sources,
                    "total": sum((s.advance_amount for s in sources), Decimal(0)),
                },
            )

        return view

    def urlpatterns(self) -> list:
        return [
            path(f"{self.document_key}s/<int:pk>/apply-advance/", self.apply_view(), name="advance_apply"),
            path("advance-applications/<int:pk>/cancel/", self.cancel_view(), name="advance_cancel"),
            path("advances/", self.list_view(), name="advances"),
        ]
