"""アップロードされた画像・動画から、OCRにかける画像（フレーム）を取り出す。"""

import io
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps, ImageStat

try:
    import pillow_heif

    pillow_heif.register_heif_opener()  # iPhone の HEIC を開けるようにする
except ImportError:  # pragma: no cover
    pass

VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".avi", ".webm", ".mkv", ".3gp"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".bmp", ".tif", ".tiff", ".gif"}


class MediaError(Exception):
    pass


def is_video(filename: str, content_type: str = "") -> bool:
    return Path(filename).suffix.lower() in VIDEO_SUFFIXES or content_type.startswith("video/")


def sharpness(image: Image.Image) -> float:
    """エッジの強さの分散。大きいほどピントが合っている。"""
    gray = image.convert("L")
    gray.thumbnail((800, 800))
    return ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES)).var[0]


def load_image(data: bytes) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as e:
        raise MediaError(
            "画像を読み込めませんでした（JPEG・PNG・HEIC などの画像か動画を選択してください）。"
        ) from e
    return ImageOps.exif_transpose(image).convert("RGB")


def video_frames(
    data: bytes, suffix: str = ".mp4", fps: float = 2, max_frames: int = 40
) -> list[Image.Image]:
    """動画から一定間隔でフレームを取り出す（ffmpeg を使用）。"""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"input{suffix or '.mp4'}"
        src.write_bytes(data)
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(src),
            "-vf",
            f"fps={fps},scale='min(1800,iw)':-2",
            "-frames:v",
            str(max_frames),
            str(Path(tmp) / "f%03d.jpg"),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except FileNotFoundError as e:
            raise MediaError(
                "動画の読み取りには ffmpeg が必要です（README の「ローカルで動かす」を参照）。"
            ) from e
        if result.returncode != 0:
            raise MediaError(f"動画からフレームを取り出せませんでした: {result.stderr.strip()[:200]}")
        frames = [Image.open(p).convert("RGB") for p in sorted(Path(tmp).glob("f*.jpg"))]
    if not frames:
        raise MediaError("動画からフレームを取り出せませんでした。")
    return frames


def best_frames(frames: list[Image.Image], count: int = 3) -> list[Image.Image]:
    """ピントの合ったフレームを選ぶ。動画の前後で偏らないよう、区間ごとに一番鮮明なものを取る。"""
    if len(frames) <= count:
        return frames
    size = len(frames) / count
    picked = []
    for i in range(count):
        segment = frames[int(i * size) : int((i + 1) * size)] or frames[-1:]
        picked.append(max(segment, key=sharpness))
    return picked


def frames_from_upload(
    data: bytes, filename: str, content_type: str = "", max_frames: int = 3
) -> list[Image.Image]:
    if is_video(filename, content_type):
        return best_frames(video_frames(data, Path(filename).suffix.lower()), max_frames)
    if Path(filename).suffix.lower() == ".pdf" or content_type == "application/pdf":
        raise MediaError(
            "PDFの読み取りには対応していません。画像（写真・スキャン）か動画を選択してください。"
        )
    return [load_image(data)]
