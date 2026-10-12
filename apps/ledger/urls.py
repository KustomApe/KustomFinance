from django.urls import path

from . import views

app_name = "ledger"
urlpatterns = [
    path("journals/", views.journal_list, name="journals"),
    path("journals/new/", views.journal_create, name="journal_new"),
    path("journals/<int:pk>/", views.journal_detail, name="journal_detail"),
    path("trial-balance/", views.trial_balance_view, name="trial_balance"),
    path("general-ledger/", views.general_ledger_view, name="general_ledger"),
    path("accounts/", views.account_list, name="accounts"),
    path("accounts/new/", views.account_edit, name="account_new"),
    path("accounts/<int:pk>/", views.account_edit, name="account_edit"),
    path("sub-accounts/<int:pk>/toggle/", views.sub_account_toggle, name="sub_account_toggle"),
    path("tax-categories/", views.tax_category_list, name="tax_categories"),
    path("closing/", views.period_close, name="period_close"),
]
