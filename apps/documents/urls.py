from django.urls import path

from . import views

app_name = "documents"
urlpatterns = [
    path("", views.search_view, name="search"),
    path("new/", views.upload, name="new"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/edit/", views.upload, name="edit"),
    path("<int:pk>/file/", views.file, name="file"),
]
