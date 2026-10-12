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
            active = request.path == url or (url != "/" and request.path.startswith(url))
            items.append({**item, "href": url, "active": active})
        if items:
            sections.append({"title": section["title"], "items": items})
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
