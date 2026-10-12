from django.conf import settings
from django.template.loader import render_to_string


def render_pdf(template: str, context: dict) -> bytes:
    # WeasyPrint はネイティブライブラリ（pango）を読み込むため、使うときだけ import する
    from weasyprint import HTML

    html = render_to_string(template, context)
    return HTML(string=html, base_url=str(settings.BASE_DIR)).write_pdf()
