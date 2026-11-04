from django.urls import path

from . import offer_views, views

app_name = "billing"

urlpatterns = [
    path("offers/", offer_views.offer_list, name="offer_list"),
    path("offers/rows/", offer_views.offer_rows, name="offer_rows"),
    path("offers/add/", offer_views.offer_add, name="offer_add"),
    path("offers/<int:pk>/edit/", offer_views.offer_edit, name="offer_edit"),
    path("offers/<int:pk>/delete/", offer_views.offer_delete, name="offer_delete"),
    path("", views.bill_list, name="bill_list"),
    path("rows/", views.bill_rows, name="bill_rows"),
    path("new/", views.bill_new, name="bill_new"),
    path("to-make/", views.bills_to_make, name="bills_to_make"),
    path("create/<int:order_id>/", views.bill_create, name="bill_create"),
    path("<int:pk>/", views.bill_detail, name="bill_detail"),
    path("<int:pk>/pay/", views.payment_add, name="payment_add"),
    path("<int:pk>/payments/<int:payment_id>/remove/", views.payment_remove, name="payment_remove"),
    path("<int:pk>/reopen/", views.bill_reopen, name="bill_reopen"),
    path("<int:pk>/cancel/", views.bill_cancel, name="bill_cancel"),
    path("<int:pk>/print/", views.bill_print, name="bill_print"),
    path("<int:pk>/print/slip/", views.bill_print_slip, name="bill_print_slip"),
]
