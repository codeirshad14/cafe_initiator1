from django.urls import path

from . import views

app_name = "web"

urlpatterns = [
    path("", views.home, name="home"),
    path("demo/", views.demo_request, name="demo_request"),
]
