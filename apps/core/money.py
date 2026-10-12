from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

from django.db import models


class Rounding(models.TextChoices):
    FLOOR = "floor", "切り捨て"
    HALF_UP = "half_up", "四捨五入"
    CEIL = "ceil", "切り上げ"


_MODES = {Rounding.FLOOR: ROUND_FLOOR, Rounding.HALF_UP: ROUND_HALF_UP, Rounding.CEIL: ROUND_CEILING}


def round_yen(value: Decimal | int, method: str = Rounding.FLOOR) -> Decimal:
    """円未満を指定方法で丸める。負数は絶対値で丸めて符号を戻す（赤伝でも同額になるように）。"""
    value = Decimal(value)
    sign = -1 if value < 0 else 1
    return abs(value).quantize(Decimal("1"), rounding=_MODES[Rounding(method)]) * sign


class MoneyField(models.DecimalField):
    """円単位の金額。"""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_digits", 15)
        kwargs.setdefault("decimal_places", 0)
        kwargs.setdefault("default", 0)
        super().__init__(*args, **kwargs)
