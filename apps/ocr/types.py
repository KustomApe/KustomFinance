import datetime
from dataclasses import asdict, dataclass, field


@dataclass
class ReceiptItem:
    name: str
    amount: int
    reduced: bool = False  # 軽減税率（8%）対象


@dataclass
class ReceiptData:
    """レシート・領収書から読み取った内容。読み取れなかった項目は空のまま。"""

    payee: str = ""
    registration_number: str = ""
    date: datetime.date | None = None
    total: int | None = None
    items: list[ReceiptItem] = field(default_factory=list)
    # 税率ごとの税込金額（{10: 1100, 8: 540}）。レシートに内訳が無ければ明細から推定する
    amount_by_rate: dict[int, int] = field(default_factory=dict)
    raw_text: str = ""
    engine: str = ""
    frames_used: int = 1
    warnings: list[str] = field(default_factory=list)

    @property
    def score(self) -> int:
        """読み取れた項目の多さ（複数フレームの結果から良いものを選ぶのに使う）。"""
        return sum(
            [bool(self.payee), bool(self.date), self.total is not None, bool(self.registration_number)]
        ) * 10 + min(len(self.items), 10)

    def as_dict(self) -> dict:
        data = asdict(self)
        data["date"] = self.date.isoformat() if self.date else ""
        data["amount_by_rate"] = {str(k): v for k, v in self.amount_by_rate.items()}
        return data
