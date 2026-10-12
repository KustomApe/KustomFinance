import csv
from urllib.parse import quote

from django.http import HttpResponse


def csv_response(filename: str, header: list[str], rows) -> HttpResponse:
    """Excelで文字化けしないよう BOM 付き UTF-8 で CSV を返す。"""
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(filename)}"
    response.write("﻿")
    writer = csv.writer(response)
    writer.writerow(header)
    writer.writerows(rows)
    return response
