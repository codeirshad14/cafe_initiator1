from django.urls import path

from . import views

app_name = "web"

urlpatterns = [
    path("", views.home, name="home"),
    path("demo/", views.demo_request, name="demo_request"),
    # a cafe's own website (each cafe its own address)
    path("cafe/<slug:slug>/", views.cafe_site, name="cafe"),
    path("cafe/<slug:slug>/feedback/", views.cafe_feedback, name="cafe_feedback"),
    # "Rate your visit": the guest's bill and three star questions, once per order
    path("feedback/<uuid:public_token>/", views.order_feedback, name="order_feedback"),
    # Cafe profile > Website and Feedback (the cafe's admin and manager)
    path("restaurant/website/", views.website_settings, name="website_settings"),
    path("restaurant/feedback/", views.feedback_list, name="feedback_list"),
    path("restaurant/feedback/<int:pk>/show/", views.feedback_show, name="feedback_show"),
]
