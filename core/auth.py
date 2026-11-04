"""Logging in with an email address.

Every staff login has its own email and password. Django's own backend
logs in by username; this one finds the user by email (any letter case).
settings.AUTHENTICATION_BACKENDS lists it first and keeps Django's after
it, so a superuser made with `createsuperuser` can still use their username.
"""

from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User


class EmailBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        email = (username or "").strip()
        if "@" not in email or password is None:
            return None  # not an email: Django's username backend tries next

        try:
            user = User.objects.get(email__iexact=email)
        except (User.DoesNotExist, User.MultipleObjectsReturned):
            # hash anyway, so an unknown email takes as long as a wrong
            # password (gives no hint which emails exist)
            User().set_password(password)
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
