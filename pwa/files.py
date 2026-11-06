"""
The installable app's own files: its icons and the Install button's script and styles.

They are served by Django at /app/<name> (pwa.views.app_file), like the manifest and
the service worker, not from /static/. So the Install button and the icons work as
soon as the new code is pulled and the app restarted, even when `collectstatic` was
forgotten on the server (that once hid the whole install feature).

The sources stay in static/ (static/img/app/, static/js/install.js, static/css/install.css).
In a page:  {% load pwa_files %}<script src="{% app_file 'install.js' %}"></script>
gives /app/install.js?v=3f9a1c0b2e: the ?v= changes with the file, so browsers keep
it for a year and still get a new version at once.
"""

import hashlib
from functools import lru_cache

from django.conf import settings
from django.contrib.staticfiles import finders
from django.urls import reverse

FILES = {
    "icon-192.png": "img/app/icon-192.png",
    "icon-512.png": "img/app/icon-512.png",
    "maskable-512.png": "img/app/maskable-512.png",
    "apple-touch-icon.png": "img/app/apple-touch-icon.png",
    "favicon-32.png": "img/app/favicon-32.png",
    "install.js": "js/install.js",
    "install.css": "css/install.css",
}
CONTENT_TYPES = {".png": "image/png", ".js": "text/javascript", ".css": "text/css"}


def source(name):
    """The file on disk (in static/), or None."""
    return finders.find(FILES[name]) if name in FILES else None


def content_type(name):
    return CONTENT_TYPES[name[name.rindex("."):]]


def _fingerprint(name):
    path = source(name)
    if not path:
        return "0"
    with open(path, "rb") as file:
        return hashlib.sha1(file.read()).hexdigest()[:10]


_kept_fingerprint = lru_cache(maxsize=None)(_fingerprint)  # the server: worked out once per start


def app_file_url(name):
    """/app/<name>?v=<fingerprint of its content>."""
    fingerprint = _fingerprint(name) if settings.DEBUG else _kept_fingerprint(name)
    return f"{reverse('pwa:app_file', args=[name])}?v={fingerprint}"
