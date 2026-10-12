from django.urls import path

from . import views

app_name = "assets"
urlpatterns = [
    path("", views.asset_list, name="list"),
    path("new/", views.asset_edit, name="new"),
    path("<int:pk>/", views.asset_detail, name="detail"),
    path("<int:pk>/edit/", views.asset_edit, name="edit"),
    path("depreciation/", views.run, name="run"),
    path("rates/", views.rate_list, name="rates"),
]
