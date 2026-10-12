"""償却率の算出（初期データ用）。"""

import math
from decimal import ROUND_HALF_UP, Decimal


def _round(value: float, places: int) -> Decimal:
    return Decimal(str(value)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def straight_line_rate(n: int) -> Decimal:
    # 1/n を小数第3位まで切り上げ（例: 6年 0.167、7年 0.143）
    return Decimal(math.ceil(1000 / n - 1e-9)) / 1000


def declining_rates(n: int) -> tuple[Decimal, Decimal, Decimal]:
    """200%定率法の (償却率, 改定償却率, 保証率)。

    償却率は 2/n を小数第3位で四捨五入。定率法の償却額が「その時点の未償却残高を残存年数で
    均等償却した額」を下回る年に改定償却率（残存年数の定額法償却率）へ切り替える。
    保証率はその切替時点の均等償却額の取得価額に対する割合。
    """
    rate = float(_round(2 / n, 3))
    if rate >= 1:
        return Decimal("1.000"), Decimal("1.000"), Decimal("0.00000")
    book = 1.0
    for year in range(1, n + 1):
        remaining = n - year + 1
        db_amount = book * rate
        sl_amount = book / remaining
        if db_amount < sl_amount - 1e-12:
            return _round(rate, 3), straight_line_rate(remaining), _round(sl_amount, 5)
        book -= db_amount
    return _round(rate, 3), Decimal("1.000"), _round(book, 5)
