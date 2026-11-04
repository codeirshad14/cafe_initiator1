from django.urls import path

from . import booking_views, views

app_name = "tables"

urlpatterns = [
    # table bookings (staff); the guest's booking pages are in orders/urls.py (/r/<slug>/book/)
    path("bookings/", booking_views.booking_list, name="booking_list"),
    path("bookings/add/", booking_views.booking_add, name="booking_add"),
    path("bookings/<int:pk>/edit/", booking_views.booking_edit, name="booking_edit"),
    path("bookings/<int:pk>/cancel/", booking_views.booking_cancel, name="booking_cancel"),
    path("bookings/<int:pk>/arrive/", booking_views.booking_arrive, name="booking_arrive"),
    path("bookings/<int:pk>/<str:step>/", booking_views.booking_step, name="booking_step"),

    path("", views.table_list, name="table_list"),
    path("rows/", views.table_rows, name="table_rows"),
    path("add/", views.table_add, name="table_add"),
    path("qr-sheet/", views.qr_sheet, name="qr_sheet"),
    path("menu-qr/<str:kind>.png", views.menu_qr, name="menu_qr"),
    path("<int:pk>/edit/", views.table_edit, name="table_edit"),
    path("<int:pk>/delete/", views.table_delete, name="table_delete"),
    path("<int:pk>/qr.png", views.table_qr, name="table_qr"),
]
