from django.urls import path

from apps.masters.doc_views import doc_urlpatterns

from . import views

app_name = "purchasing"
urlpatterns = [
    *doc_urlpatterns(views.ORDER, "orders"),
    *doc_urlpatterns(views.RECEIPT, "receipts"),
    *doc_urlpatterns(views.BILL, "bills"),
    path("orders/<int:pk>/to-receipt/", views.order_to_receipt, name="order_to_receipt"),
    path("orders/<int:pk>/to-bill/", views.order_to_bill, name="order_to_bill"),
    path("receipts/<int:pk>/to-bill/", views.receipts_to_bill, name="receipt_to_bill"),
    path("bills/<int:pk>/attachment/", views.bill_attachment, name="bill_attachment"),
    path("unbilled/", views.unbilled, name="unbilled"),
    path("unbilled/create/", views.receipts_to_bill, name="unbilled_create"),
    path("payments/", views.payment_list, name="payments"),
    path("payments/new/", views.payment_create, name="payment_new"),
    path("payments/<int:pk>/", views.payment_detail, name="payment_detail"),
    path("payables/", views.payables, name="payables"),
    path("schedule/", views.schedule, name="schedule"),
]
