from django.contrib import messages
from django.contrib.contenttypes.models import ContentType
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts import roles
from apps.accounts.permissions import require_capability
from apps.audit.models import AuditLog
from apps.audit.services import Action, record
from apps.core.exports import csv_response

from .forms import DocumentForm, SearchForm
from .models import Document
from .search import Criteria, search


@require_capability(roles.VIEW)
def search_view(request):
    form = SearchForm(request.GET or None)
    hits = []
    if form.is_bound and form.is_valid():
        hits = search(Criteria(**{k: v for k, v in form.cleaned_data.items() if v not in (None, "")}))
        if request.GET.get("format") == "csv":
            return csv_response(
                "証憑検索結果.csv",
                ["書類", "取引年月日", "取引金額", "取引先", "件名", "番号", "SHA-256", "無効"],
                [
                    [
                        h.kind,
                        h.date,
                        h.amount,
                        h.partner,
                        h.title,
                        h.number,
                        h.sha256,
                        "無効" if h.void else "",
                    ]
                    for h in hits
                ],
            )
    return render(request, "documents_store/search.html", {"form": form, "hits": hits})


@require_capability(roles.SALES_EDIT)
def upload(request, pk=None):
    doc = get_object_or_404(Document, pk=pk) if pk else None
    form = DocumentForm(request.POST or None, request.FILES or None, instance=doc)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        if not obj.pk:
            obj.uploaded_by = request.user
        obj.save()
        messages.success(request, "証憑を保存しました。")
        return redirect("documents:detail", obj.pk)
    return render(request, "documents_store/form.html", {"form": form, "object": doc})


@require_capability(roles.VIEW)
def detail(request, pk):
    doc = get_object_or_404(Document.objects.select_related("partner", "uploaded_by"), pk=pk)
    if request.method == "POST" and request.user.can(roles.LEDGER_EDIT) and not doc.is_void:
        reason = request.POST.get("reason", "").strip()
        if reason:
            doc.is_void, doc.void_reason = True, reason
            doc.save()
            record(Action.CANCEL, doc, note=f"無効: {reason}", user=request.user)
            messages.success(request, "無効にしました。")
        return redirect("documents:detail", pk)
    history = AuditLog.objects.filter(
        content_type=ContentType.objects.get_for_model(Document), object_id=str(pk)
    )
    return render(
        request, "documents_store/detail.html", {"doc": doc, "history": history.select_related("user")}
    )


@require_capability(roles.VIEW)
def file(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    return FileResponse(doc.file.open("rb"), filename=doc.file.name.rsplit("/", 1)[-1])
