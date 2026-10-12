from django.apps import apps
from django.contrib.auth.signals import user_logged_in
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .models import Action, AuditedModel
from .services import diff, record, snapshot


def _pre_save(sender, instance, raw=False, **kwargs):
    if raw or instance._state.adding or instance.pk is None:
        instance._audit_old = None
        return
    old = sender._default_manager.filter(pk=instance.pk).first()
    instance._audit_old = snapshot(old, sender.audit_exclude) if old else None


def _post_save(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    new = snapshot(instance, sender.audit_exclude)
    if created:
        record(Action.CREATE, instance, changes={k: [None, v] for k, v in new.items()})
        return
    changes = diff(getattr(instance, "_audit_old", None) or {}, new)
    if changes:
        record(Action.UPDATE, instance, changes=changes)


def _post_delete(sender, instance, **kwargs):
    old = snapshot(instance, sender.audit_exclude)
    record(Action.DELETE, instance, changes={k: [v, None] for k, v in old.items()})


def connect_audited_models() -> None:
    for model in apps.get_models():
        if issubclass(model, AuditedModel):
            uid = f"audit:{model._meta.label}"
            pre_save.connect(_pre_save, sender=model, dispatch_uid=f"{uid}:pre")
            post_save.connect(_post_save, sender=model, dispatch_uid=f"{uid}:post")
            post_delete.connect(_post_delete, sender=model, dispatch_uid=f"{uid}:del")


@receiver(user_logged_in, dispatch_uid="audit:login")
def _on_login(sender, request, user, **kwargs):
    record(Action.LOGIN, user, user=user)
