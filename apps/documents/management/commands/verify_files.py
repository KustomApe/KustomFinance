"""保存ファイルのSHA-256を再計算し、記録値と一致するか検証する（改ざん・破損の検知）。"""

from django.core.management.base import BaseCommand

from apps.core.files import file_sha256
from apps.documents.models import Document
from apps.expenses.models import ExpenseLine
from apps.purchasing.models import Bill, GoodsReceipt, PurchaseOrder
from apps.sales.models import Delivery, Estimate, Invoice, SalesOrder


class Command(BaseCommand):
    help = "保存した証憑・発行PDF・領収書のハッシュを検証します"

    def handle(self, *args, **options):
        targets = [
            (Document, "file", "file_sha256"),
            (ExpenseLine, "receipt", "receipt_sha256"),
            (Bill, "attachment", "attachment_sha256"),
        ]
        targets += [
            (m, "pdf_file", "pdf_sha256")
            for m in (Estimate, SalesOrder, Delivery, Invoice, PurchaseOrder, GoodsReceipt, Bill)
        ]
        checked = failed = 0
        for model, file_field, hash_field in targets:
            for obj in model.objects.exclude(**{file_field: ""}):
                field_file, expected = getattr(obj, file_field), getattr(obj, hash_field)
                checked += 1
                try:
                    actual = file_sha256(field_file)
                except FileNotFoundError:
                    actual = "（ファイルなし）"
                if actual != expected:
                    failed += 1
                    self.stderr.write(f"不一致: {model._meta.verbose_name} {obj} {field_file.name} {actual}")
        msg = f"{checked}件を検証、不一致 {failed}件"
        if failed:
            self.stderr.write(self.style.ERROR(msg))
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS(msg))
