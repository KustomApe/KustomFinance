import io
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image, ImageDraw, ImageFont

from apps.ocr import engines
from apps.ocr.media import best_frames, frames_from_upload

pytestmark = pytest.mark.django_db

FONTS = [
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]
FONT = next((f for f in FONTS if Path(f).exists()), None)
needs_tesseract = pytest.mark.skipif(
    not shutil.which("tesseract") or not FONT, reason="tesseract / 日本語フォントが無い"
)

LINES = [
    "カフェ・ド・テスト 渋谷店",
    "登録番号 T1234567890123",
    "2026年10月08日 14:32",
    "ブレンドコーヒー    ¥500",
    "チーズケーキ ※      ¥480",
    "10%対象 ¥500",
    "8%対象 ¥480",
    "合計              ¥980",
]


def receipt_image() -> Image.Image:
    font = ImageFont.truetype(FONT, 30)
    img = Image.new("RGB", (640, 60 + 52 * len(LINES)), "white")
    draw = ImageDraw.Draw(img)
    for i, text in enumerate(LINES):
        draw.text((30, 30 + 52 * i), text, fill="black", font=font)
    return img


def png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_best_frames_prefers_sharp_frames():
    sharp = Image.new("RGB", (200, 200), "white")
    ImageDraw.Draw(sharp).rectangle((50, 50, 150, 150), outline="black", width=3)
    blurry = sharp.resize((20, 20)).resize((200, 200))
    picked = best_frames([blurry, sharp, blurry, blurry, sharp, blurry], 2)
    assert all(p is sharp for p in picked)


def test_pdf_is_rejected():
    from apps.ocr.media import MediaError

    with pytest.raises(MediaError, match="PDF"):
        frames_from_upload(b"%PDF", "a.pdf")


@needs_tesseract
def test_tesseract_reads_generated_receipt(admin_client, settings):
    settings.OCR_ENGINE = "tesseract"
    resp = admin_client.post(
        "/ocr/receipt/", {"file": SimpleUploadedFile("r.png", png_bytes(receipt_image()))}
    )
    body = resp.json()
    assert body["ok"], body
    d = body["data"]
    assert d["total"] == 980 and d["date"] == "2026-10-08" and d["registration_number"] == "T1234567890123"
    assert "カフェ" in d["payee"]
    assert body["suggestion"]["account_name"] == "会議費"
    assert [line["rate"] for line in body["suggestion"]["lines"]] == [10, 8]


@needs_tesseract
@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg が無い")
def test_reads_video(admin_client, tmp_path, settings):
    settings.OCR_ENGINE = "tesseract"
    img = receipt_image()
    for i in range(6):
        img.save(tmp_path / f"f{i}.png")
    video = tmp_path / "r.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-y",
            "-framerate",
            "3",
            "-i",
            str(tmp_path / "f%d.png"),
            "-pix_fmt",
            "yuv420p",
            "-vf",
            "pad=ceil(iw/2)*2:ceil(ih/2)*2",
            str(video),
        ],
        check=True,
    )
    resp = admin_client.post(
        "/ocr/receipt/", {"file": SimpleUploadedFile("r.mp4", video.read_bytes(), "video/mp4")}
    )
    body = resp.json()
    assert body["ok"] and body["data"]["total"] == 980 and body["data"]["frames_used"] == 3


class FakeAnthropic:
    def __init__(self, payload=None, error=None, stop_reason="end_turn"):
        self.payload, self.error, self.stop_reason, self.calls = payload, error, stop_reason, []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def __call__(self, *args, **kwargs):
        return self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            content=[
                SimpleNamespace(type="thinking", thinking=""),
                SimpleNamespace(type="text", text=json.dumps(self.payload)),
            ],
        )


PAYLOAD = {
    "payee": "株式会社テスト商店",
    "registration_number": "T9876543210987",
    "date": "2026-10-09",
    "total": 3300,
    "amount_10": 2200,
    "amount_8": 1100,
    "items": [
        {"name": "文具", "amount": 2200, "reduced": False},
        {"name": "お茶", "amount": 1100, "reduced": True},
    ],
}


def test_claude_engine(monkeypatch, settings, admin_client):
    import anthropic

    settings.OCR_ENGINE = "claude"
    fake = FakeAnthropic(PAYLOAD)
    monkeypatch.setattr(anthropic, "Anthropic", fake)
    resp = admin_client.post(
        "/ocr/receipt/", {"file": SimpleUploadedFile("r.png", png_bytes(Image.new("RGB", (50, 50))))}
    )
    body = resp.json()
    assert body["ok"] and body["engine"] == "claude" and body["sends_externally"]
    assert body["data"]["total"] == 3300 and body["data"]["amount_by_rate"] == {"10": 2200, "8": 1100}
    request = fake.calls[0]
    assert request["model"] == settings.OCR_CLAUDE_MODEL
    assert request["output_config"]["format"]["type"] == "json_schema"
    assert request["messages"][0]["content"][0]["type"] == "image"


@needs_tesseract
def test_claude_failure_falls_back_to_tesseract(monkeypatch, settings):
    import anthropic

    settings.OCR_ENGINE = "claude"
    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropic(stop_reason="refusal", payload={}))
    data = engines.read_receipt([receipt_image()])
    assert data.engine == "tesseract" and data.total == 980
    assert "ローカルOCR" in data.warnings[0]


def test_permission_and_validation(client, make_user):
    client.force_login(make_user("viewer", "viewer"))
    assert client.post("/ocr/receipt/").status_code == 403
    client.force_login(make_user("staff", "sales"))
    assert client.post("/ocr/receipt/").json()["ok"] is False
    resp = client.post("/ocr/receipt/", {"file": SimpleUploadedFile("x.png", b"not an image")})
    assert resp.status_code == 422 and "画像を読み込めません" in resp.json()["error"]
