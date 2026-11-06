from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from core.views import StaffLoginView

admin.site.site_header = f"{settings.BRAND_NAME} admin (developer)"
admin.site.site_title = f"{settings.BRAND_NAME} admin"
admin.site.index_title = "Restaurants, memberships and logins"

urlpatterns = [
    path("admin/", admin.site.urls),
    # Django's own login / logout views (logout needs a POST)
    path("login/", StaffLoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("menu/", include("menu.urls")),
    path("tables/", include("tables.urls")),
    path("billing/", include("billing.urls")),
    path("reports/", include("reports.urls")),
    path("", include("web.urls")),     # public website at /
    path("", include("orders.urls")),  # customer QR pages: /m/<token>/, /track/<token>/
    path("", include("core.urls")),    # /home/, /dashboard/, /staff/
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
