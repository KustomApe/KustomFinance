from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models.fields.files import FieldFile

from .context import current_ip, current_user
from .models import Action, AuditLog


def snapshot(instance: models.Model, exclude: tuple[str, ...] = ()) -> dict:
    data = {}
    for field in instance._meta.concrete_fields:
        if field.name in exclude:
            continue
        value = field.value_from_object(instance)
        if isinstance(value, FieldFile):
            value = value.name
        data[field.attname if field.is_relation else field.name] = value
    return data


def diff(old: dict, new: dict) -> dict:
    return {k: [old.get(k), new.get(k)] for k in new if old.get(k) != new.get(k)}


def record(
    action: str,
    instance: models.Model | None = None,
    *,
    changes: dict | None = None,
    note: str = "",
    user=None,
) -> AuditLog:
    return AuditLog.objects.create(
        user=user or current_user.get(),
        action=action,
        content_type=ContentType.objects.get_for_model(instance) if instance else None,
        object_id=str(instance.pk) if instance else "",
        object_repr=str(instance)[:255] if instance else "",
        changes=changes or {},
        note=note,
        ip_address=current_ip.get(),
    )


__all__ = ["Action", "diff", "record", "snapshot"]
