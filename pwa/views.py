"""
The installable app (PWA): staff install Mr Cafe from the browser and it opens in
its own window, with its own icon, on Android, iPhone, Windows, Mac and Linux.

    /manifest.webmanifest   name, icons, red title bar, opens at /home/
    /sw.js                  the service worker (pwa/sw.js): must be at the site's
                            root to look after every page
    /offline/               shown when the internet is gone

The Install button (static/js/install.js) sits in the staff top bar, on the login
page and on the website. Guests' pages (QR menu, cafe website) are not part of it.
"""

import hashlib
import json

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.http import require_GET

THEME = "#da3831"       # the brand red: title bar, status bar
BACKGROUND = "#f7f5f2"  # the page colour: the splash screen while it opens

# kept ready on the device when the service worker installs
APP_FILES = ["img/app/icon-192.png", "img/app/icon-512.png", "img/app/favicon-32.png"]


@require_GET
def manifest(request):
    name = settings.BRAND_NAME
    data = {
        "id": "/home/",
        "name": f"{name} · Restaurant POS",
        "short_name": name,
        "description": "Orders, kitchen, tables, GST bills and reports for your restaurant.",
        "start_url": reverse("core:home"),
        "scope": "/",
        "display": "standalone",
        "orientation": "any",
        "theme_color": THEME,
        "background_color": BACKGROUND,
        "categories": ["business", "food", "productivity"],
        "lang": "en-IN",
        "dir": "ltr",
        "launch_handler": {"client_mode": ["navigate-existing", "auto"]},  # one window, not a new one each time
        "icons": [
            {"src": static("img/app/icon-192.png"), "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": static("img/app/icon-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": static("img/app/maskable-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }
    response = HttpResponse(json.dumps(data, indent=2), content_type="application/manifest+json")
    response["Cache-Control"] = "public, max-age=3600"
    return response


@require_GET
def service_worker(request):
    """The service worker as JavaScript. Never cached by the browser, so a new version
    reaches every device on its next visit."""
    precache = [reverse("pwa:offline")] + [static(path) for path in APP_FILES]
    # a new deploy with changed files gets a new cache name (the old one is deleted)
    version = hashlib.sha1("|".join(precache).encode()).hexdigest()[:10]
    response = render(request, "pwa/sw.js", {
        "version": version,
        "precache": json.dumps(precache),
        "offline_url": json.dumps(reverse("pwa:offline")),
        "static_url": json.dumps(settings.STATIC_URL),
    }, content_type="application/javascript")
    response["Cache-Control"] = "no-cache"
    response["Service-Worker-Allowed"] = "/"
    return response


@require_GET
def offline(request):
    """No internet: the app shows this instead of the browser's own error."""
    return render(request, "pwa/offline.html")
