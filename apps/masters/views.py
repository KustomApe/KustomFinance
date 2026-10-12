from dataclasses import dataclass

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse

from apps.accounts import roles

from .forms import DepartmentForm, ItemForm, PartnerForm, ProjectForm
from .models import Department, Item, Partner, Project


@dataclass
class Master:
    key: str
    model: type
    form_class: type
    columns: list[str]
    search_fields: list[str]
    wide_fields: str = ""


MASTERS = [
    Master(
        "partner",
        Partner,
        PartnerForm,
        ["code", "name", "is_customer", "is_supplier", "invoice_registration_number", "phone", "is_active"],
        ["code", "name", "name_kana"],
        "address notes bank_account_info",
    ),
    Master(
        "item",
        Item,
        ItemForm,
        ["code", "name", "unit", "unit_price", "purchase_price", "tax_rate", "is_active"],
        ["code", "name"],
    ),
    Master("department", Department, DepartmentForm, ["code", "name", "is_active"], ["code", "name"]),
    Master("project", Project, ProjectForm, ["code", "name", "partner", "is_active"], ["code", "name"]),
]


def _list(m: Master):
    def view(request):
        if not request.user.can(roles.VIEW):
            raise PermissionDenied
        qs = m.model.objects.all()
        if q := request.GET.get("q", "").strip():
            cond = Q()
            for f in m.search_fields:
                cond |= Q(**{f"{f}__icontains": q})
            qs = qs.filter(cond)
        if m.key == "partner" and (kind := request.GET.get("kind")) in ("customer", "supplier"):
            qs = qs.filter(**{f"is_{kind}": True})
        page = Paginator(qs, 50).get_page(request.GET.get("page"))
        fields = [m.model._meta.get_field(c) for c in m.columns]
        rows = [
            {
                "url": reverse(f"masters:{m.key}_edit", args=[o.pk]),
                "cells": [
                    (f, getattr(o, f"get_{f.name}_display")() if f.choices else getattr(o, f.name))
                    for f in fields
                ],
            }
            for o in page
        ]
        return render(
            request,
            "masters/list.html",
            {
                "m": m,
                "title": m.model._meta.verbose_name,
                "page": page,
                "headers": [f.verbose_name for f in fields],
                "rows": rows,
                "new_url": reverse(f"masters:{m.key}_new"),
            },
        )

    return view


def _edit(m: Master):
    def view(request, pk=None):
        if not request.user.can(roles.SALES_EDIT):
            raise PermissionDenied
        obj = get_object_or_404(m.model, pk=pk) if pk else None
        form = m.form_class(request.POST or None, instance=obj)
        if request.method == "POST" and form.is_valid():
            obj = form.save()
            messages.success(request, f"{m.model._meta.verbose_name}「{obj}」を保存しました。")
            return redirect(f"masters:{m.key}_list")
        return render(
            request,
            "masters/form.html",
            {
                "m": m,
                "title": m.model._meta.verbose_name,
                "form": form,
                "object": obj,
                "list_url": reverse(f"masters:{m.key}_list"),
            },
        )

    return view


def master_urlpatterns():
    patterns = []
    for m in MASTERS:
        prefix = f"{m.key.replace('_', '-')}s"
        patterns += [
            path(f"{prefix}/", _list(m), name=f"{m.key}_list"),
            path(f"{prefix}/new/", _edit(m), name=f"{m.key}_new"),
            path(f"{prefix}/<int:pk>/", _edit(m), name=f"{m.key}_edit"),
        ]
    return patterns
