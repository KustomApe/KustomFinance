import datetime

from apps.ocr.parsing import merge_results, normalize, parse_receipt_text
from apps.ocr.types import ReceiptData

SUPERMARKET = """
ス ー パ ー マ ー ケ ッ ト 渋 谷 店
TEL 03-1234-5678
登録番号 T1234-5678-90123
2026年10月 8日(木) 18:42
牛乳                    ¥258 ※
食パン                  ¥198 ※
洗剤                    ¥429
小計                  ¥885
(10%対象              ¥472)
(8%対象               ¥491)
合計                   ¥963
お預り               ¥1,000
お釣り                  ¥37
※は軽減税率対象商品です
"""

CAFE_RECEIPT = """
領 収 書
株式会社カフェテリア
R8.10.5
コーヒー 2点 @500     ¥1,000
ケーキ               ¥650
お会計              ¥1,650
(内消費税等         ¥150)
"""

TAXI = """
東京交通株式会社
2026/10/03 22:15
運賃 ¥3,200
合 計
¥3,500
"""


def test_supermarket_receipt():
    r = parse_receipt_text(SUPERMARKET)
    assert r.payee == "スーパーマーケット渋谷店"
    assert r.registration_number == "T1234567890123"
    assert r.date == datetime.date(2026, 10, 8)
    assert r.total == 963
    assert [(i.name, i.amount, i.reduced) for i in r.items] == [
        ("牛乳", 258, True),
        ("食パン", 198, True),
        ("洗剤", 429, False),
    ]
    assert r.amount_by_rate == {10: 472, 8: 491}


def test_cafe_receipt_with_reiwa_date():
    r = parse_receipt_text(CAFE_RECEIPT)
    assert r.payee == "株式会社カフェテリア"
    assert r.date == datetime.date(2026, 10, 5)
    assert r.total == 1650
    assert [i.name for i in r.items] == ["コーヒー 2点", "ケーキ"]
    assert r.amount_by_rate == {10: 1650}


def test_total_on_next_line():
    r = parse_receipt_text(TAXI)
    assert r.total == 3500 and r.payee == "東京交通株式会社"
    assert r.date == datetime.date(2026, 10, 3)


def test_total_fallback_from_items():
    r = parse_receipt_text("文具店\nノート ¥300\nペン ¥150\n")
    assert r.total == 450 and r.warnings


def test_normalize_removes_spaces_between_japanese():
    assert normalize("合 計  ¥１，２３４") == "合計  ¥1,234"


def test_merge_results_votes_on_total():
    a = ReceiptData(payee="店", total=1000, date=datetime.date(2026, 1, 1))
    b = ReceiptData(
        payee="店", total=1080, date=datetime.date(2026, 1, 1), registration_number="T1234567890123"
    )
    c = ReceiptData(payee="店", total=1080)
    merged = merge_results([a, b, c])
    assert merged.total == 1080 and merged.registration_number == "T1234567890123" and merged.frames_used == 3


def test_tesseract_quirks():
    # 実際の Tesseract の出力で見られた化け方
    text = (
        "カフ ェ ・ ド ・ テ スト 渋谷 店\n登録 番号 「1234567890123\n2026 年 10 月 08 日\n"
        "ブレ ンド コー ヒー \\500\nサン ドイ ツ ッ チ ※ ¥650\n10% 対 象 \\500\n合計 \\1.630\n"
    )
    r = parse_receipt_text(text)
    assert r.total == 1630
    assert r.registration_number == "T1234567890123"
    assert r.date == datetime.date(2026, 10, 8)
    assert ("サンドイツッチ", 650, True) in [(i.name, i.amount, i.reduced) for i in r.items]


def test_drops_garbage_items_when_sum_exceeds_total():
    r = parse_receipt_text("店\nコーヒー ¥500\nBHO ¥370\n合計 ¥500\n")
    assert [i.name for i in r.items] == ["コーヒー"]
