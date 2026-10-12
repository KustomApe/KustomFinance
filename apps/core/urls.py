from django.urls import path

from . import views

app_name = "core"
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("settings/company/", views.company_edit, name="company"),
    path("settings/fiscal-years/", views.fiscal_year_list, name="fiscal_years"),
    path("settings/fiscal-years/new/", views.fiscal_year_edit, name="fiscal_year_new"),
    path("settings/fiscal-years/<int:pk>/", views.fiscal_year_edit, name="fiscal_year_edit"),
]
