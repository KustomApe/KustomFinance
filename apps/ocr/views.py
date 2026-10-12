from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from apps.accounts import roles

from .engines import OcrError, read_receipt
from .media import MediaError, frames_from_upload
from .suggest import suggestion


@require_POST
def receipt(request):
    """レシートの画像・動画を受け取り、読み取った内容を JSON で返す（保存はしない）。"""
    if not (request.user.can(roles.EXPENSE_SUBMIT) or request.user.can(roles.SALES_EDIT)):
        raise PermissionDenied
    upload = request.FILES.get("file")
    if not upload:
        return JsonResponse({"ok": False, "error": "ファイルを選択してください。"}, status=400)
    if upload.size > settings.OCR_MAX_UPLOAD_MB * 1024 * 1024:
        return JsonResponse(
            {"ok": False, "error": f"ファイルが大きすぎます（{settings.OCR_MAX_UPLOAD_MB}MBまで）。"},
            status=400,
        )
    try:
        frames = frames_from_upload(upload.read(), upload.name, upload.content_type or "")
        data = read_receipt(frames)
    except (MediaError, OcrError) as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=422)
    return JsonResponse(
        {
            "ok": True,
            "data": data.as_dict(),
            "suggestion": suggestion(data),
            "engine": data.engine,
            "sends_externally": settings.OCR_ENGINE == "claude",
        }
    )
