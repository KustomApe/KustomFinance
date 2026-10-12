from django.core.paginator import Paginator
from django.shortcuts import render

from apps.accounts import roles
from apps.accounts.permissions import require_capability

from .models import Action, AuditLog


@require_capability(roles.LEDGER_EDIT)
def log_list(request):
    logs = AuditLog.objects.select_related("user", "content_type")
    action = request.GET.get("action")
    if action:
        logs = logs.filter(action=action)
    if q := request.GET.get("q"):
        logs = logs.filter(object_repr__icontains=q)
    if date_from := request.GET.get("from"):
        logs = logs.filter(timestamp__date__gte=date_from)
    if date_to := request.GET.get("to"):
        logs = logs.filter(timestamp__date__lte=date_to)
    page = Paginator(logs, 50).get_page(request.GET.get("page"))
    return render(request, "audit/log_list.html", {"page": page, "actions": Action.choices})
