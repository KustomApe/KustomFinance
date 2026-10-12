from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("audit/", include("apps.audit.urls")),
    path("ledger/", include("apps.ledger.urls")),
    path("masters/", include("apps.masters.urls")),
    path("sales/", include("apps.sales.urls")),
    path("purchasing/", include("apps.purchasing.urls")),
    path("expenses/", include("apps.expenses.urls")),
    path("banking/", include("apps.banking.urls")),
    path("assets/", include("apps.assets.urls")),
    path("documents/", include("apps.documents.urls")),
    path("reports/", include("apps.reports.urls")),
    path("", include("apps.core.urls")),
]
