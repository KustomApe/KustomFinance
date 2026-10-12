from django.apps import AppConfig


class AuditConfig(AppConfig):
    name = "apps.audit"
    verbose_name = "操作ログ"

    def ready(self) -> None:
        from . import signals

        signals.connect_audited_models()
