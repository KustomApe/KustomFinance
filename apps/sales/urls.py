from django.urls import path

from apps.masters.doc_views import doc_urlpatterns

from . import views

app_name = "sales"
urlpatterns = [
    *views.ADVANCES.urlpatterns(),
    *doc_urlpatterns(views.ESTIMATE, "estimates"),
    *doc_urlpatterns(views.ORDER, "orders"),
    *doc_urlpatterns(views.DELIVERY, "deliveries"),
    *doc_urlpatterns(views.INVOICE, "invoices"),
    path("estimates/<int:pk>/to-order/", views.estimate_to_order, name="estimate_to_order"),
    path("orders/<int:pk>/to-delivery/", views.order_to_delivery, name="order_to_delivery"),
    path("orders/<int:pk>/to-invoice/", views.order_to_invoice, name="order_to_invoice"),
    path("deliveries/<int:pk>/to-invoice/", views.deliveries_to_invoice, name="delivery_to_invoice"),
    path("billing/", views.billing, name="billing"),
    path("billing/create/", views.deliveries_to_invoice, name="billing_create"),
    path("receipts/", views.receipt_list, name="receipts"),
    path("receipts/new/", views.receipt_create, name="receipt_new"),
    path("receipts/<int:pk>/", views.receipt_detail, name="receipt_detail"),
    path("receivables/", views.receivables, name="receivables"),
]
