from decimal import Decimal

from django import template
from django.urls import NoReverseMatch, reverse

from apps.core.navigation import NAV

register = template.Library()


@register.simple_tag(takes_context=True)
def nav_sections(context):
    request = context["request"]
    sections = []
    for section in NAV:
        items = []
        for item in section["items"]:
            if item.get("cap") and not request.user.can(item["cap"]):
                continue
            try:
                url = reverse(item["url"])
            except NoReverseMatch:
                continue
            items.append({**item, "href": url, "active": False})
        if items:
            sections.append({"title": section["title"], "items": items})
    # 現在のパスに最も長く一致するメニューだけを選択状態にする
    matches = [
        item
        for s in sections
        for item in s["items"]
        if request.path == item["href"] or (item["href"] != "/" and request.path.startswith(item["href"]))
    ]
    if matches:
        max(matches, key=lambda item: len(item["href"]))["active"] = True
    return sections


@register.filter
def yen(value):
    """金額を 1,234 形式で表示（負数は △1,234）。"""
    if value in (None, ""):
        return ""
    value = Decimal(value)
    text = f"{abs(value):,.0f}"
    return f"△{text}" if value < 0 else text


@register.filter
def can(user, capability):
    return user.can(capability)


@register.filter
def qty(value):
    """数量・単価: 小数部が0なら整数表示、それ以外は必要な桁だけ表示。"""
    if value in (None, ""):
        return ""
    value = Decimal(value)
    if value == value.to_integral():
        return f"{value:,.0f}"
    return f"{value.normalize():,f}"


@register.filter
def cell(value):
    if value is True:
        return "✓"
    if value is False:
        return ""
    if isinstance(value, Decimal):
        return qty(value)
    return "" if value is None else value
