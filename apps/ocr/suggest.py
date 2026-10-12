"""読み取った内容から勘定科目・税区分を提案する（あくまで初期値。申請者が確認して直す）。"""

from apps.ledger.models import Account, TaxCategory

from .types import ReceiptData

KEYWORDS = [
    (
        [
            "交通",
            "タクシー",
            "JR",
            "鉄道",
            "バス",
            "新幹線",
            "航空",
            "ANA",
            "JAL",
            "駐車",
            "高速",
            "ETC",
            "Suica",
            "PASMO",
        ],
        "旅費交通費",
    ),
    (["ホテル", "旅館", "宿泊", "イン"], "旅費交通費"),
    (["郵便", "切手", "ゆうパック", "宅急便", "ヤマト", "佐川", "運輸"], "荷造運賃"),
    (["カフェ", "コーヒー", "珈琲", "喫茶", "Cafe", "CAFE", "スターバックス", "ドトール"], "会議費"),
    (["居酒屋", "レストラン", "寿司", "焼肉", "ダイニング", "バー", "BAR"], "接待交際費"),
    (["書店", "書房", "ブックス", "新聞", "雑誌"], "新聞図書費"),
    (
        [
            "文具",
            "ステーショナリー",
            "コピー",
            "トナー",
            "インク",
            "ヨドバシ",
            "ビックカメラ",
            "ホームセンター",
            "ダイソー",
            "100円",
            "Amazon",
            "アスクル",
        ],
        "消耗品費",
    ),
    (["携帯", "通信", "docomo", "au", "SoftBank", "インターネット"], "通信費"),
    (["ガソリン", "ENEOS", "出光", "コスモ石油", "給油"], "旅費交通費"),
]


def suggest_account(data: ReceiptData) -> Account | None:
    text = " ".join([data.payee, *(i.name for i in data.items)])
    for words, account_name in KEYWORDS:
        if any(w in text for w in words):
            return Account.objects.filter(name=account_name, is_active=True).first()
    return Account.objects.filter(name="消耗品費", is_active=True).first()


def tax_code_for_rate(rate: int) -> str:
    return "P8R" if rate == 8 else "P10"


def suggestion(data: ReceiptData) -> dict:
    account = suggest_account(data)
    taxes = {t.code: t.pk for t in TaxCategory.objects.filter(code__in=["P10", "P8R"])}
    lines = []
    for rate, amount in sorted(data.amount_by_rate.items(), key=lambda kv: -kv[0]):
        lines.append({"rate": rate, "amount": amount, "tax_category_id": taxes.get(tax_code_for_rate(rate))})
    return {
        "account_id": account.pk if account else None,
        "account_name": account.name if account else "",
        "lines": lines,
    }
