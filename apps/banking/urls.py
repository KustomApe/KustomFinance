from django.urls import path

from . import views

app_name = "banking"
urlpatterns = [
    path("import/", views.import_view, name="import"),
    path("transactions/", views.transactions, name="transactions"),
    path("transactions/<int:pk>/action/", views.transaction_action, name="transaction_action"),
    path("transactions/<int:pk>/form/", views.manual_form, name="manual_form"),
    path("reconciliation/", views.reconciliation, name="reconciliation"),
    *views.settings_urlpatterns(),
]
