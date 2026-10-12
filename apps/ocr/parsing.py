"""OCRで得たテキストからレシートの項目を取り出す（日本のレシート・領収書の一般的な書式向け）。"""

import datetime
import re
import unicodedata
from collections import Counter

from .types import ReceiptData, ReceiptItem

# 円は小数を使わないので、OCRで「,」が「.」に化けた 1.630 も 1,630 として読む
_AMOUNT = r"[¥￥\\]?\s*(-?\d{1,3}(?:[,，.]\d{3})+|-?\d+)\s*円?"
AMOUNT_AT_END = re.compile(_AMOUNT + r"\s*[*※軽]?\s*[)）]?\s*$")
_JA = "\u3005\u3040-\u30ff\u3400-\u9fff"  # ひらがな・カタカナ・漢字
TOTAL_KEYWORDS = [
    "総合計",
    "合計金額",
    "税込合計",
    "お買上計",
    "お買上げ計",
    "お会計",
    "ご請求額",
    "ご請求金額",
    "領収金額",
    "合計",
    "計",
]
NOT_TOTAL = [
    "小計",
    "内税",
    "消費税",
    "税額",
    "対象",
    "預",
    "釣",
    "おつり",
    "お返し",
    "値引",
    "割引",
    "点数",
    "ポイント",
]
NOT_ITEM = NOT_TOTAL + [
    "合計",
    "計",
    "現金",
    "クレジット",
    "カード",
    "支払",
    "電子マネー",
    "QR",
    "PayPay",
    "税",
    "TEL",
    "電話",
    "登録番号",
    "No.",
    "伝票",
    "レジ",
    "担当",
]
CORP_HINTS = [
    "株式会社",
    "(株)",
    "有限会社",
    "(有)",
    "合同会社",
    "店",
    "堂",
    "屋",
    "商店",
    "カフェ",
    "Cafe",
    "CAFE",
    "ストア",
    "マート",
    "薬局",
    "書店",
    "ホテル",
    "交通",
    "タクシー",
    "レストラン",
    "食堂",
]
SKIP_HEADER = [
    "領収書",
    "領収証",
    "レシート",
    "お買上",
    "毎度",
    "ありがとう",
    "いらっしゃいませ",
    "様",
    "TEL",
    "電話",
    "〒",
    "登録番号",
]


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    # Tesseract は日本語の文字の間に空白を入れがちなので、和文同士の間の空白を詰める
    text = re.sub(rf"(?<=[{_JA}])[ \t]+(?=[{_JA}])", "", text)
    text = text.replace("，", ",").replace("．", ".")
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def parse_amount(text: str) -> int | None:
    m = AMOUNT_AT_END.search(text)
    if not m:
        return None
    try:
        return int(re.sub(r"[,.]", "", m.group(1)))
    except ValueError:
        return None


def parse_date(text: str) -> datetime.date | None:
    patterns = [
        (r"(令和|R)\s*(\d{1,2}|元)\s*[年./\-]\s*(\d{1,2})\s*[月./\-]\s*(\d{1,2})", "reiwa"),
        (r"(20\d{2})\s*[年./\-]\s*(\d{1,2})\s*[月./\-]\s*(\d{1,2})", "western"),
        (r"(?<!\d)(\d{2})[./](\d{1,2})[./](\d{1,2})(?!\d)", "short"),
    ]
    for pattern, kind in patterns:
        for m in re.finditer(pattern, text):
            try:
                if kind == "reiwa":
                    year = 2018 + (1 if m.group(2) == "元" else int(m.group(2)))
                    return datetime.date(year, int(m.group(3)), int(m.group(4)))
                if kind == "western":
                    return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                return datetime.date(2000 + int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                continue
    return None


def parse_registration_number(text: str) -> str:
    # OCRで「T 1234-5678-...」のように区切られることがある
    # 「T」が「丁」「「」「t」に化けることがある。「登録番号」の後ろの13桁も拾う
    m = re.search(r"(?:[Tt丁「]|登録番号\s*[:：]?)\s*((?:\d[\s\-]?){13})(?!\d)", text)
    if not m:
        return ""
    digits = re.sub(r"\D", "", m.group(1))
    return f"T{digits}" if len(digits) == 13 else ""


def _has_any(line: str, words) -> bool:
    return any(w in line for w in words)


def find_total(lines: list[str]) -> int | None:
    for keyword in TOTAL_KEYWORDS:
        candidates = []
        for i, line in enumerate(lines):
            label = AMOUNT_AT_END.sub("", line)
            if keyword in label and not _has_any(label, NOT_TOTAL):
                amount = parse_amount(line)
                # 「合計」の金額が次の行に出るレシートもある
                if amount is None and i + 1 < len(lines):
                    amount = parse_amount(lines[i + 1])
                if amount is not None and amount > 0:
                    candidates.append(amount)
        if candidates:
            return max(candidates)
    return None


def find_payee(lines: list[str]) -> str:
    head = lines[:8]
    for line in head:
        if _has_any(line, CORP_HINTS) and not _has_any(line, SKIP_HEADER) and not parse_date(line):
            return re.sub(r"\s+", " ", line)[:100]
    for line in head:
        if (
            len(line) >= 2
            and not _has_any(line, SKIP_HEADER)
            and not parse_date(line)
            and not re.fullmatch(r"[\d\s\-:/.()]+", line)
            and parse_amount(line) is None
        ):
            return re.sub(r"\s+", " ", line)[:100]
    return ""


def find_items(lines: list[str], total: int | None) -> list[ReceiptItem]:
    items = []
    for line in lines:
        amount = parse_amount(line)
        if amount is None or amount == 0:
            continue
        name = AMOUNT_AT_END.sub("", line).strip(" .:・*※()（）")
        name = re.sub(r"\s*[@x×]\s*\d+.*$", "", name)  # 「@120 x2」などの単価表示を落とす
        if len(name) < 1 or _has_any(name, NOT_ITEM) or parse_date(line):
            continue
        if total is not None and abs(amount) > total:
            continue
        reduced = bool(re.search(r"[*※軽]|8%|\(8\)", line))
        items.append(ReceiptItem(name=name[:100], amount=amount, reduced=reduced))
    if total is not None and sum(i.amount for i in items) > total:
        # 明細の合計が総額を超えるのは誤読が混じっているため。日本語を含まない短い行（記号の誤読）を除く
        items = [i for i in items if re.search(f"[{_JA}]", i.name) or len(i.name) >= 4]
    return items


def find_amount_by_rate(lines: list[str]) -> dict[int, int]:
    """「10%対象 ¥1,100」「8%対象 ¥540」のような税率別の対象額。"""
    result = {}
    for line in lines:
        m = re.search(r"(10|8)\s*%\s*(?:対象|タイショウ)", line)
        if m:
            amount = parse_amount(line)
            if amount:
                result.setdefault(int(m.group(1)), amount)
    return result


def parse_receipt_text(text: str) -> ReceiptData:
    clean = normalize(text)
    lines = clean.splitlines()
    data = ReceiptData(raw_text=clean)
    data.date = parse_date(clean)
    data.registration_number = parse_registration_number(clean)
    data.total = find_total(lines)
    data.payee = find_payee(lines)
    data.items = find_items(lines, data.total)
    data.amount_by_rate = find_amount_by_rate(lines)
    if data.total is None and data.items:
        data.total = sum(i.amount for i in data.items)
        data.warnings.append("合計が読み取れなかったため、明細の合計を表示しています。")
    if not data.amount_by_rate and data.total is not None:
        reduced = sum(i.amount for i in data.items if i.reduced)
        if reduced and reduced < data.total:
            data.amount_by_rate = {8: reduced, 10: data.total - reduced}
        elif reduced and reduced >= data.total:
            data.amount_by_rate = {8: data.total}
        else:
            data.amount_by_rate = {10: data.total}
    return data


def merge_results(results: list[ReceiptData]) -> ReceiptData:
    """動画の複数フレームの結果をまとめる。金額・日付は多数決、その他は最も多く読めたフレームを採用する。"""
    if len(results) == 1:
        return results[0]
    best = max(results, key=lambda r: r.score)
    for attr in ("total", "date"):
        values = [getattr(r, attr) for r in results if getattr(r, attr)]
        if values:
            setattr(best, attr, Counter(values).most_common(1)[0][0])
    if not best.registration_number:
        best.registration_number = next((r.registration_number for r in results if r.registration_number), "")
    best.frames_used = len(results)
    return best
