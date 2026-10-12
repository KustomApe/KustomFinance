import datetime

from django.db import IntegrityError, transaction

from .models import Company, NumberSequence

PREFIXES = {
    "estimate": "EST",
    "sales_order": "SO",
    "delivery": "DN",
    "invoice": "INV",
    "receipt": "RCV",
    "purchase_order": "PO",
    "goods_receipt": "GR",
    "bill": "BILL",
    "payment": "PAY",
    "expense": "EXP",
    "journal": "JE",
    "asset": "FA",
    "document": "DOC",
}


def next_number(key: str, date: datetime.date) -> str:
    """`INV-2026-00001` 形式の番号を発行する。

    行ロックで採番するため同時発行でも重複せず、呼び出し元のトランザクションが
    ロールバックされれば番号も戻る（欠番が出ない）。
    """
    year = Company.load().fiscal_year_of(date)
    with transaction.atomic():
        seq = NumberSequence.objects.select_for_update().filter(key=key, year=year).first()
        if seq is None:
            try:
                with transaction.atomic():
                    NumberSequence.objects.create(key=key, year=year)
            except IntegrityError:
                pass  # 同時に別リクエストが作成した
            seq = NumberSequence.objects.select_for_update().get(key=key, year=year)
        seq.last_number += 1
        seq.save(update_fields=["last_number"])
    return f"{PREFIXES.get(key, key.upper())}-{year}-{seq.last_number:05d}"
