from django.urls import path

from tables import booking_views

from . import delivery_views, guest_views, notification_views, staff_views

app_name = "orders"

urlpatterns = [
    # the restaurant's public menu, for sharing (no login): take away, delivery, table booking
    path("r/<slug:slug>/", guest_views.public_menu, name="public_menu"),
    path("r/<slug:slug>/dish/<int:item_id>/", guest_views.public_dish, name="public_dish"),
    path("r/<slug:slug>/view/", guest_views.menu_view, name="menu_view"),
    path("r/<slug:slug>/view/dish/<int:item_id>/", guest_views.view_dish, name="view_dish"),
    path("r/<slug:slug>/book/", booking_views.public_booking, name="public_booking"),
    path("booking/<uuid:public_token>/", booking_views.booking_status, name="booking_status"),

    # customer pages, opened from the table's QR code (no login)
    path("m/<uuid:qr_token>/", guest_views.customer_menu, name="customer_menu"),
    path("m/<uuid:qr_token>/dish/<int:item_id>/", guest_views.dish_detail, name="dish_detail"),
    path("m/<uuid:qr_token>/cart/put/<int:item_id>/", guest_views.cart_put, name="cart_put"),
    path("m/<uuid:qr_token>/cart/", guest_views.cart_view, name="cart_view"),
    path("m/<uuid:qr_token>/cart/add/<int:item_id>/", guest_views.cart_add, name="cart_add"),
    path("m/<uuid:qr_token>/cart/remove/<int:item_id>/", guest_views.cart_remove, name="cart_remove"),
    path("m/<uuid:qr_token>/place/", guest_views.order_place, name="order_place"),
    path("m/<uuid:qr_token>/track/", guest_views.order_track_lookup, name="order_track_lookup"),
    path("track/<uuid:public_token>/", guest_views.order_track, name="order_track"),

    # staff: floor and tables
    path("floor/", staff_views.floor, name="floor"),
    path("floor/table/<int:table_id>/", staff_views.floor_table, name="floor_table"),
    path("floor/order/<int:order_id>/", staff_views.floor_order, name="floor_order"),
    path("orders/<int:order_id>/cancel/", staff_views.order_cancel, name="order_cancel"),

    # staff: waiter takes an order, waiter's ready list
    path("waiter/takeaway/", staff_views.waiter_takeaway, name="waiter_takeaway"),
    path("waiter/order/<int:table_id>/", staff_views.waiter_order, name="waiter_order"),
    path("waiter/order/<int:table_id>/add/<int:item_id>/", staff_views.waiter_cart_add, name="waiter_cart_add"),
    path("waiter/order/<int:table_id>/remove/<int:item_id>/", staff_views.waiter_cart_remove, name="waiter_cart_remove"),
    path("waiter/order/<int:table_id>/place/", staff_views.waiter_order_place, name="waiter_order_place"),
    path("waiter/ready/", staff_views.waiter_ready, name="waiter_ready"),

    # staff: home delivery, and the rider's own screen
    path("deliveries/", delivery_views.deliveries, name="deliveries"),
    path("deliveries/new/", delivery_views.delivery_new, name="delivery_new"),
    path("deliveries/<int:order_id>/reject/", delivery_views.delivery_reject, name="delivery_reject"),
    path("deliveries/<int:order_id>/<str:step>/", delivery_views.delivery_step, name="delivery_step"),
    path("rider/", delivery_views.rider_home, name="rider_home"),

    # staff: kitchen and KOTs
    path("kitchen/", staff_views.kitchen, name="kitchen"),
    path("kitchen/stock/", staff_views.kitchen_stock, name="kitchen_stock"),
    path("kot/<int:kot_id>/status/<str:status>/", staff_views.kot_status, name="kot_status"),
    path("kot/<int:kot_id>/print/", staff_views.kot_print, name="kot_print"),
    path("kot/<int:kot_id>/print/slip/", staff_views.kot_print_slip, name="kot_print_slip"),

    # staff: the bell in the top bar (new orders)
    path("notifications/", notification_views.notification_bell, name="notification_bell"),
    path("notifications/<int:pk>/open/", notification_views.notification_open, name="notification_open"),
    path("notifications/read-all/", notification_views.notification_read_all, name="notification_read_all"),
]
