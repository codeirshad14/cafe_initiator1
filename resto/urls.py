from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.contrib.auth import views as auth_views
from django.urls import include, path, reverse

from core.views import StaffLoginView

admin.site.site_header = f"{settings.BRAND_NAME} admin (developer)"
admin.site.site_title = f"{settings.BRAND_NAME} admin"
admin.site.index_title = "Restaurants, memberships and logins"


def admin_login(request, extra_context=None, _login=admin.site.login):
    """The admin's own login always goes on into the admin. Its form (Jazzmin) sends no
    "next", and without one Django opened the cafe app's Home instead, which has nothing for
    the developer ("This is the developer login"). The admin also keeps a login of its own,
    apart from the cafe app's (core/middleware.py)."""
    if not (request.POST.get(REDIRECT_FIELD_NAME) or request.GET.get(REDIRECT_FIELD_NAME)):
        request.GET = request.GET.copy()
        request.GET[REDIRECT_FIELD_NAME] = reverse("admin:index")
    return _login(request, extra_context)


admin.site.login = admin_login  # (before admin.site.urls below reads it)

urlpatterns = [
    path("admin/", admin.site.urls),
    # Django's own login / logout views (logout needs a POST)
    path("login/", StaffLoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("menu/", include("menu.urls")),
    path("tables/", include("tables.urls")),
    path("billing/", include("billing.urls")),
    path("reports/", include("reports.urls")),
    path("", include("pwa.urls")),     # the installable app: /manifest.webmanifest, /sw.js, /offline/
    path("", include("web.urls")),     # public website at /
    path("", include("orders.urls")),  # customer QR pages: /m/<token>/, /track/<token>/
    path("", include("core.urls")),    # /home/, /dashboard/, /staff/
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
