"""
The developer's Django admin (/admin/) keeps a login of its own, apart from the cafe app's.

A browser keeps one Django login (the session cookie). When the developer signed in to
/admin/ as the superuser (to add a cafe, renew a membership, during an update ...), that
replaced the restaurant staff's login in the same browser, and the app then showed "This is
the developer login" until they logged out and in again. Here every /admin/ request uses
cookies of its own (mrcafe_admin_session, mrcafe_admin_csrftoken): signing in or out of the
admin never touches the app's login, nor the other way round.

The cookie names are swapped on the way in (before the session and CSRF middleware read
them) and back on the way out (after they set them). MIDDLEWARE lists this before
SessionMiddleware.
"""

from django.conf import settings
from django.urls import reverse

ADMIN_SESSION = "mrcafe_admin_session"
ADMIN_CSRF = "mrcafe_admin_csrftoken"
COPIED = ("expires", "max-age", "path", "domain", "secure", "httponly", "samesite")


class SeparateAdminLogin:
    def __init__(self, get_response):
        self.get_response = get_response
        self.prefix = None

    def is_admin(self, request):
        if self.prefix is None:
            self.prefix = reverse("admin:index")  # "/admin/"
        return request.path.startswith(self.prefix)

    def __call__(self, request):
        if not self.is_admin(request):
            return self.get_response(request)
        names = {settings.SESSION_COOKIE_NAME: ADMIN_SESSION, settings.CSRF_COOKIE_NAME: ADMIN_CSRF}
        cookies = request.COOKIES
        for app_name, admin_name in names.items():  # the admin's own cookies, under the usual names
            if admin_name in cookies:
                cookies[app_name] = cookies[admin_name]
            else:
                cookies.pop(app_name, None)

        response = self.get_response(request)

        for app_name, admin_name in names.items():  # set back under the admin's names
            morsel = response.cookies.pop(app_name, None)
            if morsel is None:
                continue
            response.cookies[admin_name] = morsel.value
            for key in COPIED:
                if morsel[key]:
                    response.cookies[admin_name][key] = morsel[key]
        return response
