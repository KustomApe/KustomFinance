"""OCRエンジン。既定はローカルで完結する Tesseract。

OCR_ENGINE=claude にすると Claude API（画像認識）で読み取る。精度は高いが、
レシートの画像が Anthropic に送信される。API キーは ANTHROPIC_API_KEY などから読む。
"""

import base64
import datetime
import io
import json
import logging
import os
import subprocess
import tempfile

from django.conf import settings
from PIL import Image, ImageOps

from .parsing import merge_results, parse_receipt_text
from .types import ReceiptData, ReceiptItem

logger = logging.getLogger(__name__)


class OcrError(Exception):
    pass


# ---- Tesseract（ローカル） ----


def _prepare_for_tesseract(image: Image.Image) -> Image.Image:
    gray = ImageOps.autocontrast(image.convert("L"), cutoff=1)
    if gray.width < 1200:  # 細長いレシートは拡大したほうが読みやすい
        ratio = 1600 / gray.width
        gray = gray.resize((1600, int(gray.height * ratio)), Image.Resampling.LANCZOS)
    return gray


def tesseract_text(image: Image.Image) -> str:
    env = dict(os.environ)
    if settings.OCR_TESSDATA_DIR:
        env["TESSDATA_PREFIX"] = str(settings.OCR_TESSDATA_DIR)
    with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
        _prepare_for_tesseract(image).save(tmp.name)
        try:
            result = subprocess.run(
                ["tesseract", tmp.name, "stdout", "-l", "jpn+eng", "--psm", "4"],
                capture_output=True,
                text=True,
                timeout=120,
                env=env,
            )
        except FileNotFoundError as e:
            raise OcrError(
                "Tesseract がインストールされていません（README の「ローカルで動かす」を参照）。"
            ) from e
    if result.returncode != 0:
        raise OcrError(f"Tesseract の実行に失敗しました: {result.stderr.strip()[:200]}")
    return result.stdout


def read_with_tesseract(frames: list[Image.Image]) -> ReceiptData:
    results = [parse_receipt_text(tesseract_text(frame)) for frame in frames]
    data = merge_results(results)
    data.engine = "tesseract"
    return data


# ---- Claude API ----

RECEIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "payee": {"type": "string", "description": "発行者（店名・会社名）。不明なら空文字"},
        "registration_number": {
            "type": "string",
            "description": "適格請求書発行事業者登録番号（T+13桁）。無ければ空文字",
        },
        "date": {"type": "string", "description": "取引日 YYYY-MM-DD。不明なら空文字"},
        "total": {"type": "integer", "description": "支払総額（税込、円）。不明なら -1"},
        "amount_10": {"type": "integer", "description": "10%対象の税込金額。不明なら -1"},
        "amount_8": {"type": "integer", "description": "8%（軽減税率）対象の税込金額。不明なら -1"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "amount": {"type": "integer", "description": "その行の金額（円）"},
                    "reduced": {"type": "boolean", "description": "軽減税率（8%）対象なら true"},
                },
                "required": ["name", "amount", "reduced"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["payee", "registration_number", "date", "total", "amount_10", "amount_8", "items"],
    "additionalProperties": False,
}

CLAUDE_PROMPT = (
    "日本のレシートまたは領収書の画像です（同じレシートを写した複数の画像の場合があります）。"
    "経費精算に使うため、書かれている内容だけを読み取ってください。推測で値を補わず、読めない項目は空文字または -1 にします。"
    "items には購入した品目の行だけを入れ、小計・合計・消費税・お預り・お釣りの行は入れません。"
    "「※」「*」「軽」などの印は軽減税率（8%）対象を表します。"
)


def _image_block(image: Image.Image) -> dict:
    copy = image.copy()
    copy.thumbnail((1568, 1568))
    buffer = io.BytesIO()
    copy.save(buffer, format="JPEG", quality=90)
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/jpeg",
            "data": base64.standard_b64encode(buffer.getvalue()).decode(),
        },
    }


def read_with_claude(frames: list[Image.Image]) -> ReceiptData:
    import anthropic

    client = anthropic.Anthropic()
    try:
        response = client.beta.messages.create(
            model=settings.OCR_CLAUDE_MODEL,
            max_tokens=8000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": RECEIPT_SCHEMA}},
            messages=[
                {
                    "role": "user",
                    "content": [
                        *(_image_block(f) for f in frames[:3]),
                        {"type": "text", "text": CLAUDE_PROMPT},
                    ],
                }
            ],
        )
    except anthropic.AuthenticationError as e:
        raise OcrError("Claude API の認証に失敗しました（ANTHROPIC_API_KEY を確認してください）。") from e
    except anthropic.RateLimitError as e:
        raise OcrError("Claude API の利用上限に達しました。しばらくしてから再度お試しください。") from e
    except anthropic.APIStatusError as e:
        raise OcrError(f"Claude API でエラーが発生しました（{e.status_code}）。") from e
    except anthropic.APIConnectionError as e:
        raise OcrError("Claude API に接続できませんでした。") from e
    if response.stop_reason == "refusal":
        raise OcrError("Claude API がこの画像の読み取りを行いませんでした。")
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as e:
        raise OcrError("Claude API の応答を読み取れませんでした。") from e
    data = ReceiptData(
        payee=raw["payee"].strip(),
        registration_number=raw["registration_number"].replace(" ", "").replace("-", ""),
        total=raw["total"] if raw["total"] >= 0 else None,
        items=[ReceiptItem(i["name"], i["amount"], i["reduced"]) for i in raw["items"]],
        amount_by_rate={rate: v for rate, v in ((10, raw["amount_10"]), (8, raw["amount_8"])) if v > 0},
        raw_text=json.dumps(raw, ensure_ascii=False, indent=1),
        engine="claude",
        frames_used=len(frames[:3]),
    )
    if raw["date"]:
        try:
            data.date = datetime.date.fromisoformat(raw["date"])
        except ValueError:
            data.warnings.append(f"日付を解釈できませんでした: {raw['date']}")
    if not data.amount_by_rate and data.total:
        data.amount_by_rate = {10: data.total}
    if data.registration_number and not (
        len(data.registration_number) == 14 and data.registration_number[1:].isdigit()
    ):
        data.warnings.append(f"登録番号の形式が正しくありません: {data.registration_number}")
        data.registration_number = ""
    return data


def read_receipt(frames: list[Image.Image]) -> ReceiptData:
    if settings.OCR_ENGINE == "claude":
        try:
            return read_with_claude(frames)
        except OcrError as e:
            logger.warning("Claude OCR failed, falling back to tesseract: %s", e)
            data = read_with_tesseract(frames)
            data.warnings.insert(0, f"{e} ローカルOCR（Tesseract）で読み取りました。")
            return data
    return read_with_tesseract(frames)
