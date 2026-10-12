"""売掛金・買掛金の年齢表（支払期日からの経過日数で集計）。"""

import datetime
from decimal import Decimal

BUCKETS = [
    ("期日内", None, 0),
    ("1〜30日", 1, 30),
    ("31〜60日", 31, 60),
    ("61〜90日", 61, 90),
    ("91日以上", 91, None),
]
LABELS = [b[0] for b in BUCKETS]


def bucket_index(overdue_days: int) -> int:
    return next(
        i
        for i, (_, lo, hi) in enumerate(BUCKETS)
        if (lo is None or overdue_days >= lo) and (hi is None or overdue_days <= hi)
    )


def aging_rows(documents, as_of: datetime.date) -> tuple[list[dict], list[Decimal]]:
    """未決済の帳票（outstanding / due_date / partner を持つ）を取引先ごと・期間別に集計する。"""
    rows: dict[int, dict] = {}
    for doc in documents:
        outstanding = doc.outstanding
        if outstanding <= 0:
            continue
        overdue = (as_of - (doc.due_date or doc.issue_date)).days
        row = rows.setdefault(
            doc.partner_id,
            {
                "partner": doc.partner,
                "buckets": [Decimal(0)] * len(BUCKETS),
                "total": Decimal(0),
                "documents": [],
            },
        )
        row["buckets"][bucket_index(overdue)] += outstanding
        row["total"] += outstanding
        row["documents"].append((doc, outstanding, overdue))
    result = sorted(rows.values(), key=lambda r: r["partner"].code)
    totals = [sum((r["buckets"][i] for r in result), Decimal(0)) for i in range(len(BUCKETS))]
    return result, totals
