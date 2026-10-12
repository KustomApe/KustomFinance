"""帳票の保存・発行・取消・複製（販売・購買共通）。"""

import hashlib
from collections.abc import Callable

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from apps.audit.services import Action, record
from apps.core.models import Company
from apps.core.numbering import next_number
from apps.core.pdf import render_pdf

from .documents import DocStatus, TradeDocument
from .models import TaxRate

LINE_FIELDS = ["item", "transaction_date", "description", "quantity", "unit", "unit_price", "tax_rate"]
HEADER_COPY_FIELDS = ["partner", "subject", "notes", "department", "project"]


def sales_tax_code(rate: str) -> str:
    return {
        TaxRate.STANDARD: "S10",
        TaxRate.REDUCED: "S8R",
        TaxRate.EXEMPT: "SNT",
        TaxRate.EXPORT: "SEX",
    }.get(rate, "OUT")


@transaction.atomic
def save_document(doc: TradeDocument, lines: list[dict]) -> TradeDocument:
    """下書きの帳票と明細を保存し、合計・税率別内訳を再計算する。"""
    if doc.pk and doc.status != DocStatus.DRAFT:
        raise ValidationError("発行済みの帳票は編集できません。")
    if not lines:
        raise ValidationError("明細を1行以上入力してください。")
    doc.save()
    doc.lines.all().delete()
    for i, data in enumerate(lines):
        doc.lines.create(sort_order=i, **{f: data.get(f) for f in LINE_FIELDS if f in data})
    doc.recalculate(Company.load().tax_rounding)
    doc.save()
    return doc


def document_pdf(doc: TradeDocument, template: str) -> bytes:
    lines = list(doc.lines.all())
    return render_pdf(
        template,
        {
            "doc": doc,
            "company": Company.load(),
            "lines": lines,
            "has_dates": any(line.transaction_date for line in lines),
        },
    )


@transaction.atomic
def issue_document(
    doc: TradeDocument, template: str, *, user=None, on_issue: Callable | None = None
) -> TradeDocument:
    """採番・確定し、発行時点のPDFを控えとして保存する（電子帳簿保存法の保存要件）。"""
    doc = type(doc).objects.select_for_update().get(pk=doc.pk)
    if doc.status != DocStatus.DRAFT:
        raise ValidationError("下書きの帳票のみ発行できます。")
    if not doc.lines.exists():
        raise ValidationError("明細がありません。")
    doc.recalculate(Company.load().tax_rounding)
    doc.number = next_number(doc.number_key, doc.issue_date)
    doc.status = DocStatus.ISSUED
    doc.issued_at = timezone.now()
    if on_issue:
        on_issue(doc, user)
    pdf = document_pdf(doc, template)
    doc.pdf_sha256 = hashlib.sha256(pdf).hexdigest()
    doc.pdf_file.save(f"{doc.number}.pdf", ContentFile(pdf), save=False)
    doc.save()
    record(Action.CONFIRM, doc, note=f"{doc.title}を発行（PDF SHA-256: {doc.pdf_sha256}）", user=user)
    return doc


@transaction.atomic
def cancel_document(doc: TradeDocument, reason: str, *, user=None, on_cancel: Callable | None = None):
    doc = type(doc).objects.select_for_update().get(pk=doc.pk)
    if doc.status != DocStatus.ISSUED:
        raise ValidationError("発行済みの帳票のみ取り消せます。")
    if not reason.strip():
        raise ValidationError("取消理由を入力してください。")
    if on_cancel:
        on_cancel(doc, reason, user)
    doc.status = DocStatus.CANCELLED
    doc.cancelled_at = timezone.now()
    doc.cancel_reason = reason
    doc.save()
    record(Action.CANCEL, doc, note=reason, user=user)
    return doc


@transaction.atomic
def copy_document(
    source: TradeDocument, target_model, *, user=None, line_date=None, **fields
) -> TradeDocument:
    """帳票の内容を別の帳票（見積→受注→納品→請求など）の下書きとして複製する。"""
    target = target_model(
        **{f: getattr(source, f) for f in HEADER_COPY_FIELDS},
        status=DocStatus.DRAFT,
        created_by=user,
        **fields,
    )
    lines = [
        {
            **{f: getattr(line, f) for f in LINE_FIELDS},
            **({"transaction_date": line_date} if line_date else {}),
        }
        for line in source.lines.all()
    ]
    return save_document(target, lines)
