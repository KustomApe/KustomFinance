import datetime
import io
import zipfile
from decimal import Decimal
from urllib.parse import unquote

import pytest

from apps.masters.doc_services import save_document
from apps.masters.models import Partner
from apps.sales.models import Invoice

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def media(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path


def draft(partner):
    return save_document(
        Invoice(partner=partner, issue_date=datetime.date(2026, 10, 1)),
        [{"description": "作業", "quantity": Decimal(1), "unit_price": Decimal(10000), "tax_rate": "10"}],
    )


def test_issue_and_download(admin_client, fiscal_years):
    partner = Partner.objects.create(code="C1", name="株式会社ダウンロード")
    inv = draft(partner)
    resp = admin_client.get(f"/sales/invoices/{inv.pk}/pdf/?download=1")
    assert resp.status_code == 200 and resp["Content-Disposition"].startswith("attachment")
    assert "下書き" in unquote(resp["Content-Disposition"])

    resp = admin_client.post(f"/sales/invoices/{inv.pk}/issue/", {"download": "1"})
    assert resp.status_code == 302 and resp.url.endswith("?download=1")
    page = admin_client.get(resp.url).content.decode()
    assert "pdf/?download=1" in page and "PDFをダウンロード" in page

    resp = admin_client.get(f"/sales/invoices/{inv.pk}/pdf/?download=1")
    disposition = unquote(resp["Content-Disposition"])
    assert (
        disposition.startswith("attachment")
        and "請求書_INV-2026-00001_株式会社ダウンロード.pdf" in disposition
    )
    assert b"".join(resp.streaming_content)[:4] == b"%PDF"
    resp = admin_client.get(f"/sales/invoices/{inv.pk}/pdf/")
    assert resp["Content-Disposition"].startswith("inline")


def test_zip_download(admin_client, fiscal_years):
    partner = Partner.objects.create(code="C1", name="株式会社ZIP")
    issued = [draft(partner) for _ in range(2)]
    for inv in issued:
        admin_client.post(f"/sales/invoices/{inv.pk}/issue/")
    unissued = draft(partner)
    resp = admin_client.post("/sales/invoices/pdf-zip/", {"ids": [i.pk for i in issued] + [unissued.pk]})
    assert resp["Content-Type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(resp.content)).namelist()
    assert sorted(names) == ["請求書_INV-2026-00001_株式会社ZIP.pdf", "請求書_INV-2026-00002_株式会社ZIP.pdf"]
    resp = admin_client.post("/sales/invoices/pdf-zip/", {"ids": [unissued.pk]})
    assert resp.status_code == 302
    assert admin_client.get("/sales/invoices/").status_code == 200
