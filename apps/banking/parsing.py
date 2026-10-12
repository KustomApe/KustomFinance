"""銀行明細CSVの読み取り。"""

import csv
import datetime
import io
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

ERAS = {"R": 2018, "令和": 2018, "H": 1988, "平成": 1988}


def decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp932"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("文字コードを判別できません（UTF-8 または Shift_JIS のCSVを指定してください）。")


def parse_date(text: str) -> datetime.date:
    s = unicodedata.normalize("NFKC", text).strip()
    m = re.fullmatch(r"(令和|平成|[RH])\s*(\d{1,2})[./\-年](\d{1,2})[./\-月](\d{1,2})日?", s)
    if m:
        return datetime.date(ERAS[m[1]] + int(m[2]), int(m[3]), int(m[4]))
    m = re.fullmatch(r"(\d{4})[./\-年](\d{1,2})[./\-月](\d{1,2})日?", s)
    if m:
        return datetime.date(int(m[1]), int(m[2]), int(m[3]))
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", s)
    if m:
        return datetime.date(int(m[1]), int(m[2]), int(m[3]))
    raise ValueError(f"日付を読み取れません: {text}")


def parse_amount(text: str) -> Decimal:
    s = unicodedata.normalize("NFKC", text or "").strip().replace(",", "").replace("円", "").replace("¥", "")
    s = s.replace("\\", "").replace(" ", "")
    if s in ("", "-"):
        return Decimal(0)
    negative = s.startswith("△") or s.startswith("▲") or (s.startswith("(") and s.endswith(")"))
    s = s.strip("△▲()")
    try:
        value = Decimal(s)
    except InvalidOperation as e:
        raise ValueError(f"金額を読み取れません: {text}") from e
    return -value if negative else value


@dataclass
class ParsedRow:
    line_no: int
    date: datetime.date
    description: str
    deposit: Decimal
    withdrawal: Decimal
    balance: Decimal | None


def parse_csv(data: bytes, profile) -> tuple[list[ParsedRow], list[str]]:
    reader = csv.reader(io.StringIO(decode(data)))
    rows, errors = [], []

    def col(record, index):
        return record[index - 1] if index and index <= len(record) else ""

    for line_no, record in enumerate(reader, 1):
        if line_no <= profile.skip_rows or not any(c.strip() for c in record):
            continue
        try:
            date = parse_date(col(record, profile.date_column))
            if profile.amount_column:
                amount = parse_amount(col(record, profile.amount_column))
                deposit, withdrawal = (amount, Decimal(0)) if amount >= 0 else (Decimal(0), -amount)
            else:
                deposit = parse_amount(col(record, profile.deposit_column))
                withdrawal = parse_amount(col(record, profile.withdrawal_column))
            balance_text = col(record, profile.balance_column).strip()
            balance = parse_amount(balance_text) if balance_text else None
        except ValueError as e:
            errors.append(f"{line_no}行目: {e}")
            continue
        if not deposit and not withdrawal:
            continue
        description = unicodedata.normalize("NFKC", col(record, profile.description_column)).strip()
        rows.append(ParsedRow(line_no, date, description, deposit, withdrawal, balance))
    return rows, errors


_SMALL = str.maketrans("ァィゥェォャュョッヮ", "アイウエオヤユヨツワ")
_CORP = re.compile(
    r"(カブシキガイシヤ|ユウゲンガイシヤ|ゴウドウガイシヤ|カ\)|\(カ|ユ\)|\(ユ|ド\)|\(ド|株式会社|有限会社|合同会社)"
)


def normalize_name(text: str) -> str:
    """振込名義の照合用に正規化（全角化・小書き文字・法人格・記号の除去）。"""
    s = unicodedata.normalize("NFKC", text or "").upper()
    s = "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in s)  # ひらがな→カタカナ
    s = s.translate(_SMALL)
    s = _CORP.sub("", s)
    return re.sub(r"[\s・.,()（）\-ー]", "", s)
