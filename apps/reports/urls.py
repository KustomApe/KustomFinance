from django.urls import path

from . import views

app_name = "reports"
urlpatterns = [
    path("pl/", views.pl_view, name="pl"),
    path("bs/", views.bs_view, name="bs"),
    path("tax/", views.tax_view, name="tax"),
]
