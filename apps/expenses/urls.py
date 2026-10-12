from django.urls import path

from . import views

app_name = "expenses"
urlpatterns = [
    path("", views.claim_list, name="list"),
    path("new/", views.claim_edit, name="new"),
    path("<int:pk>/", views.claim_detail, name="detail"),
    path("<int:pk>/edit/", views.claim_edit, name="edit"),
    path("receipts/<int:pk>/", views.receipt_file, name="receipt"),
]
