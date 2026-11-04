from django.urls import path

from . import views

app_name = "menu"

urlpatterns = [
    
    path("categories/", views.category_list, name="category_list"),
    path("categories/rows/", views.category_rows, name="category_rows"),
    path("categories/add/", views.category_add, name="category_add"),
    path("categories/<int:pk>/edit/", views.category_edit, name="category_edit"),
    path("categories/<int:pk>/delete/", views.category_delete, name="category_delete"),

    path("items/", views.menu_item_list, name="menu_item_list"),
    path("items/rows/", views.menu_item_rows, name="menu_item_rows"),
    path("items/add/", views.menu_item_add, name="menu_item_add"),
    path("items/<int:pk>/edit/", views.menu_item_edit, name="menu_item_edit"),
    path("items/<int:pk>/delete/", views.menu_item_delete, name="menu_item_delete"),
    path("items/<int:pk>/toggle/", views.menu_item_toggle, name="menu_item_toggle"),
]
