"""証憑の検索（電子帳簿保存法の検索要件: 取引年月日・取引金額・取引先、範囲指定・組合せ）。

保存した証憑のほか、発行した帳票（PDF控え）・受領した仕入請求書・経費の領収書を横断して検索する。
"""

import datetime
from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Q
from django.urls import reverse

from apps.expenses.models import ExpenseLine
from apps.masters.documents import DocStatus
from apps.purchasing.models import Bill, GoodsReceipt, PurchaseOrder
from apps.sales.models import Delivery, Estimate, Invoice, SalesOrder

from .models import Document


@dataclass
class Hit:
    kind: str
    date: datetime.date
    amount: Decimal
    partner: str
    title: str
    number: str
    detail_url: str
    file_url: str
    sha256: str
    void: bool = False


@dataclass
class Criteria:
    date_from: datetime.date | None = None
    date_to: datetime.date | None = None
    amount_min: Decimal | None = None
    amount_max: Decimal | None = None
    partner: str = ""
    kind: str = ""


TRADE_SOURCES = [
    ("sales", "estimate", Estimate, "見積書（発行）"),
    ("sales", "order", SalesOrder, "注文請書（発行）"),
    ("sales", "delivery", Delivery, "納品書（発行）"),
    ("sales", "invoice", Invoice, "請求書（発行）"),
    ("purchasing", "order", PurchaseOrder, "注文書（発行）"),
    ("purchasing", "receipt", GoodsReceipt, "検収書"),
]

KIND_CHOICES = [
    ("document", "保存した証憑"),
    *[(f"{ns}:{key}", label) for ns, key, _, label in TRADE_SOURCES],
    ("bill", "請求書（受領）"),
    ("expense", "経費の領収書"),
]


def _range(qs, field: str, lo, hi):
    if lo is not None:
        qs = qs.filter(**{f"{field}__gte": lo})
    if hi is not None:
        qs = qs.filter(**{f"{field}__lte": hi})
    return qs


def search(c: Criteria, limit: int = 500) -> list[Hit]:
    hits: list[Hit] = []
    want = lambda key: not c.kind or c.kind == key  # noqa: E731

    if want("document"):
        qs = _range(
            _range(Document.objects.select_related("partner"), "transaction_date", c.date_from, c.date_to),
            "amount",
            c.amount_min,
            c.amount_max,
        )
        if c.partner:
            qs = qs.filter(Q(partner__name__icontains=c.partner) | Q(partner_name__icontains=c.partner))
        for d in qs[:limit]:
            hits.append(
                Hit(
                    d.get_kind_display(),
                    d.transaction_date,
                    d.amount,
                    d.display_partner,
                    d.title,
                    "",
                    reverse("documents:detail", args=[d.pk]),
                    reverse("documents:file", args=[d.pk]),
                    d.file_sha256,
                    d.is_void,
                )
            )

    def trade(qs, label, ns, key, file_url):
        qs = _range(
            _range(
                qs.exclude(status=DocStatus.DRAFT).select_related("partner"),
                "issue_date",
                c.date_from,
                c.date_to,
            ),
            "total",
            c.amount_min,
            c.amount_max,
        )
        if c.partner:
            qs = qs.filter(partner__name__icontains=c.partner)
        for d in qs[:limit]:
            hits.append(
                Hit(
                    label,
                    d.issue_date,
                    d.total,
                    d.partner.name,
                    d.subject,
                    d.number,
                    reverse(f"{ns}:{key}_detail", args=[d.pk]),
                    file_url(d),
                    getattr(d, "attachment_sha256", "") or d.pdf_sha256,
                    d.status == DocStatus.CANCELLED,
                )
            )

    for ns, key, model, label in TRADE_SOURCES:
        if want(f"{ns}:{key}"):
            trade(
                model.objects.all(),
                label,
                ns,
                key,
                lambda d, ns=ns, key=key: reverse(f"{ns}:{key}_pdf", args=[d.pk]),
            )
    if want("bill"):
        trade(
            Bill.objects.all(),
            "請求書（受領）",
            "purchasing",
            "bill",
            lambda d: (
                reverse("purchasing:bill_attachment", args=[d.pk])
                if d.attachment
                else reverse("purchasing:bill_pdf", args=[d.pk])
            ),
        )

    if want("expense"):
        qs = _range(
            _range(
                ExpenseLine.objects.exclude(receipt="").select_related("claim"),
                "date",
                c.date_from,
                c.date_to,
            ),
            "amount",
            c.amount_min,
            c.amount_max,
        )
        if c.partner:
            qs = qs.filter(payee__icontains=c.partner)
        for ln in qs[:limit]:
            hits.append(
                Hit(
                    "領収書（経費）",
                    ln.date,
                    ln.amount,
                    ln.payee,
                    ln.description,
                    ln.claim.number or "",
                    reverse("expenses:detail", args=[ln.claim_id]),
                    reverse("expenses:receipt", args=[ln.pk]),
                    ln.receipt_sha256,
                    ln.claim.status == "cancelled",
                )
            )

    hits.sort(key=lambda h: (h.date, h.number), reverse=True)
    return hits[:limit]
