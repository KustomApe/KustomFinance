from django.urls import path

from . import views

app_name = "ocr"
urlpatterns = [path("receipt/", views.receipt, name="receipt")]
