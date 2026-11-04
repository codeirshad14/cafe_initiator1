from django.urls import path

from . import location_views, locations, printer_views, views

app_name = "core"

urlpatterns = [
    path("printers/", printer_views.printers, name="printers"),
    path("printers/test/", printer_views.printer_test_slip, name="printer_test_slip"),
    path("printers/helper.zip", printer_views.print_helper_download, name="print_helper_download"),
    path("home/", views.home, name="home"),
    path("live/", views.live, name="live"),
    path("location/", locations.switch_location, name="switch_location"),
    path("locations/", location_views.location_list, name="location_list"),
    path("locations/rows/", location_views.location_rows, name="location_rows"),
    path("locations/add/", location_views.location_add, name="location_add"),
    path("locations/<int:pk>/edit/", location_views.location_edit, name="location_edit"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("restaurant/", views.restaurant_settings, name="restaurant_settings"),
    path("restaurant/bill/", views.bill_settings, name="bill_settings"),
    path("staff/", views.staff_list, name="staff_list"),
    path("staff/rows/", views.staff_rows, name="staff_rows"),
    path("staff/usage/", views.staff_usage, name="staff_usage"),
    path("staff/add/", views.staff_add, name="staff_add"),
    path("staff/<int:pk>/edit/", views.staff_edit, name="staff_edit"),
]
