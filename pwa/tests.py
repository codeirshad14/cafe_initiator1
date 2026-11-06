import json

from django.contrib.staticfiles import finders
from django.test import Client, TestCase

from core.testing import client_for, make_restaurant, make_staff, make_table


class InstallableAppTests(TestCase):
    """The app installs from the browser (manifest + service worker) and works offline-safe."""

    def test_manifest_has_what_browsers_need_to_install(self):
        response = Client().get("/manifest.webmanifest")
        self.assertEqual(response["Content-Type"], "application/manifest+json")
        app = json.loads(response.content)
        self.assertEqual(app["short_name"], "Mr Cafe")
        self.assertEqual((app["start_url"], app["scope"], app["display"]), ("/home/", "/", "standalone"))
        self.assertEqual(app["theme_color"], "#da3831")
        sizes = {(icon["sizes"], icon["purpose"]) for icon in app["icons"]}
        self.assertTrue({("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")} <= sizes)
        for icon in app["icons"]:  # from /app/, never waiting for collectstatic
            self.assertRegex(icon["src"], r"^/app/[a-z0-9-]+\.png\?v=[0-9a-f]{10}$")
            self.assertEqual(Client().get(icon["src"]).status_code, 200)
        self.assertEqual(app["related_applications"],
                         [{"platform": "webapp", "url": "http://testserver/manifest.webmanifest"}])

    def test_every_icon_file_exists(self):
        for name in ("icon-192.png", "icon-512.png", "maskable-512.png", "apple-touch-icon.png", "favicon-32.png"):
            with self.subTest(name=name):
                self.assertIsNotNone(finders.find(f"img/app/{name}"))

    def test_service_worker_is_at_the_root_and_never_stored(self):
        response = Client().get("/sw.js")
        self.assertEqual(response["Content-Type"], "application/javascript")
        self.assertEqual(response["Cache-Control"], "no-cache")
        self.assertEqual(response["Service-Worker-Allowed"], "/")
        body = response.content.decode()
        self.assertIn('const OFFLINE_URL = "/offline/"', body)
        self.assertRegex(body, r'"/app/icon-192.png\?v=[0-9a-f]{10}"')
        self.assertIn('const FILE_PREFIXES = ["/static/", "/app/"]', body)
        self.assertIn('request.method !== "GET"', body)  # forms are never touched

    def test_offline_page_needs_nothing_from_the_internet(self):
        page = Client().get("/offline/")
        self.assertContains(page, "No internet")
        self.assertNotContains(page, "https://")

    def test_install_button_on_staff_pages_login_and_website(self):
        restaurant = make_restaurant()
        staff_page = client_for(make_staff(restaurant, "MANAGER")).get("/dashboard/")
        for page in (staff_page, Client().get("/login/"), Client().get("/")):
            with self.subTest(page=page.request["PATH_INFO"]):
                self.assertContains(page, 'rel="manifest" href="/manifest.webmanifest"')
                self.assertContains(page, "data-install-app hidden")
                self.assertContains(page, 'id="installHelp"')
                self.assertRegex(page.content.decode(), r'<script src="/app/install.js\?v=[0-9a-f]{10}">')
                self.assertRegex(page.content.decode(), r'href="/app/install.css\?v=[0-9a-f]{10}"')

    def test_app_files_come_from_django_with_a_fingerprint(self):
        for name, kind in (("install.js", "text/javascript"), ("install.css", "text/css"),
                           ("icon-192.png", "image/png"), ("apple-touch-icon.png", "image/png")):
            with self.subTest(name=name):
                kept = Client().get(f"/app/{name}?v=abc")
                self.assertEqual((kept.status_code, kept["Content-Type"]), (200, kind))
                self.assertIn("immutable", kept["Cache-Control"])
                self.assertNotIn("immutable", Client().get(f"/app/{name}")["Cache-Control"])
        for name in ("settings.py", "../manage.py", "app.css"):  # only the app's own files
            self.assertEqual(Client().get(f"/app/{name}").status_code, 404)

    def test_the_button_always_shows_and_explains_an_installed_app(self):
        script = b"".join(Client().get("/app/install.js").streaming_content).decode()
        self.assertIn("button.hidden = false", script)
        self.assertIn("getInstalledRelatedApps", script)
        page = Client().get("/login/")
        for steps in ("android", "chrome", "edge", "ios", "mac", "samsung", "firefox", "other"):
            self.assertContains(page, f'data-install-for="{steps}"')
        self.assertContains(page, "Already installed? Install it fresh")
        self.assertContains(page, "data-install-done hidden")

    def test_guests_pages_are_not_the_staff_app(self):
        restaurant = make_restaurant()
        table = make_table(restaurant)
        for url in (f"/m/{table.qr_token}/", f"/r/{restaurant.slug}/"):
            with self.subTest(url=url):
                page = Client().get(url)
                self.assertEqual(page.status_code, 200)
                self.assertNotContains(page, "manifest.webmanifest")
