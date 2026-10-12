from contextvars import ContextVar

current_user: ContextVar = ContextVar("audit_current_user", default=None)
current_ip: ContextVar[str | None] = ContextVar("audit_current_ip", default=None)
