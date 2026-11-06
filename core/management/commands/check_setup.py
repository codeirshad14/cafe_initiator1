"""
python manage.py check_setup

Run on the server when something does not work (error 500, a login that will not
go in). It checks what the app needs there and prints OK or FAIL, with the fix:

  settings     DEBUG, SECRET_KEY, ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS
  database     it answers, and every migration is applied
  files        the static files were collected (also the new ones after a git pull);
               media/ and the cache can be written
  pages        the website, the login page and the app files open without error 500
  logins      every restaurant has an admin login that can sign in (its own email,
               a password, switched on, membership running), and no email belongs
               to two logins (then neither can sign in)

Nothing is changed. Exit code 1 when something failed.
"""

import os
import tempfile

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.staticfiles import finders
from django.contrib.staticfiles.storage import staticfiles_storage
from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.db import DEFAULT_DB_ALIAS, connections
from django.db.migrations.executor import MigrationExecutor
from django.db.models import Count
from django.db.models.functions import Lower
from django.template.loader import render_to_string
from django.test import Client

from core.models import Restaurant, Staff


class Command(BaseCommand):
    help = "Check the server's settings, database, files and logins (changes nothing)."

    def handle(self, *args, **options):
        self.failed = 0
        for part in (self.check_settings, self.check_database, self.check_files, self.check_pages, self.check_logins):
            part()
        if self.failed:
            self.stdout.write(self.style.ERROR(f"\n{self.failed} problem(s). Fix them, then: sudo bash deploy/update.sh"))
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS("\nAll good."))

    # ------------------------------------------------------------ helpers
    def ok(self, text):
        self.stdout.write(f"  OK    {text}")

    def fail(self, text, fix):
        self.failed += 1
        self.stdout.write(self.style.ERROR(f"  FAIL  {text}"))
        self.stdout.write(f"        fix: {fix}")

    def head(self, text):
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{text}"))

    # ------------------------------------------------------------ settings
    def check_settings(self):
        self.head("Settings (.env)")
        if settings.DEBUG:
            self.fail("DEBUG is True: error pages show your settings to anyone", "DEBUG=False in .env (on the server)")
        else:
            self.ok("DEBUG is False")
        key = settings.SECRET_KEY
        if len(key) < 40 or "put-" in key or "paste-" in key:
            self.fail("SECRET_KEY is short or still the example text",
                      'python3 -c "import secrets; print(secrets.token_urlsafe(50))" and put it in .env')
        else:
            self.ok("SECRET_KEY is set")
        hosts = [host for host in settings.ALLOWED_HOSTS if host not in ("127.0.0.1", "localhost")]
        if hosts:
            self.ok(f"ALLOWED_HOSTS: {', '.join(settings.ALLOWED_HOSTS)}")
        else:
            self.fail("ALLOWED_HOSTS has no domain: the site answers 400", "ALLOWED_HOSTS=your-domain in .env")
        if settings.SESSION_COOKIE_SECURE:
            self.ok("login cookies are https:// only: staff must open https://your-domain/login/ "
                    "(until HTTPS works: SECURE_COOKIES=False in .env)")
        missing = [host for host in hosts if f"https://{host}" not in settings.CSRF_TRUSTED_ORIGINS]
        if missing:
            self.fail(f"CSRF_TRUSTED_ORIGINS lacks https://{missing[0]}: forms (and login) answer 403",
                      f"CSRF_TRUSTED_ORIGINS=https://{missing[0]} in .env")
        elif hosts:
            self.ok("CSRF_TRUSTED_ORIGINS matches the domain")

    # ------------------------------------------------------------ database
    def check_database(self):
        self.head("Database")
        connection = connections[DEFAULT_DB_ALIAS]
        try:
            connection.ensure_connection()
        except Exception as error:
            self.fail(f"cannot connect: {str(error).strip().splitlines()[0]}",
                      "check DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT in .env (and that PostgreSQL runs)")
            return
        self.ok(f"connected ({connection.vendor}, database {connection.settings_dict['NAME']})")
        waiting = MigrationExecutor(connection).migration_plan(MigrationExecutor(connection).loader.graph.leaf_nodes())
        if waiting:
            names = ", ".join(f"{migration.app_label}.{migration.name}" for migration, _ in waiting[:3])
            self.fail(f"{len(waiting)} migration(s) not applied ({names}…): pages answer 500",
                      "python manage.py migrate")
        else:
            self.ok("every migration is applied")

    # ------------------------------------------------------------ files
    def check_files(self):
        self.head("Files")
        try:
            url = staticfiles_storage.url("css/app.css")
            self.ok(f"static files found (css/app.css -> {url})")
        except Exception as error:
            self.fail(f"static files: {error}", "python manage.py collectstatic --noinput")
        self.check_collected()
        for name, folder in (("media (photos, logos)", settings.MEDIA_ROOT),
                             ("cache (wrong-password counts)", settings.CACHES["default"].get("LOCATION") or "")):
            if not folder or not os.path.isabs(str(folder)):
                continue  # the in-memory cache (development): nothing on disk
            try:
                os.makedirs(folder, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=folder):
                    pass
                self.ok(f"{name} can be written: {folder}")
            except OSError as error:
                self.fail(f"{name} cannot be written: {folder} ({error.strerror})",
                          f"sudo mkdir -p {folder} && sudo chown -R <app user> {folder}")
        try:
            cache.set("check-setup", 1, 5)
            cache.delete("check-setup")
            self.ok("cache works")
        except Exception as error:
            self.fail(f"cache: {error}", "make CACHE_DIR writable, or leave it out of .env")
        try:
            render_to_string("500.html")
            self.ok("error pages render")
        except Exception as error:
            self.fail(f"the 500 page cannot render: {error}", "python manage.py collectstatic --noinput")

    def check_collected(self):
        """Every static file of the code is in collectstatic's list (a `git pull` brought new
        ones: icons, scripts). Only on the server, where names get a fingerprint."""
        collected = getattr(staticfiles_storage, "hashed_files", None)
        if collected is None:
            return  # development: files are served straight from static/
        missing = sorted({path.replace("\\", "/")
                          for finder in finders.get_finders()
                          for path, _ in finder.list(["CVS", ".*", "*~"])} - set(collected))
        if missing:
            self.fail(f"{len(missing)} static file(s) not collected yet, e.g. {', '.join(missing[:3])}",
                      "python manage.py collectstatic --noinput")
        else:
            self.ok("every static file is collected")

    # ------------------------------------------------------------ pages
    def check_pages(self):
        """Open the public pages as a browser would (inside this command, no internet needed)."""
        self.head("Pages")
        hosts = [host for host in settings.ALLOWED_HOSTS if host not in ("127.0.0.1", "localhost", "*")]
        browser = Client(HTTP_HOST=(hosts or ["localhost"])[0].lstrip("."))
        for url in ("/", "/login/", "/manifest.webmanifest", "/sw.js", "/offline/", "/app/install.js", "/app/icon-192.png"):
            try:
                status = browser.get(url, secure=True).status_code
            except Exception as error:
                self.fail(f"{url} answers 500: {type(error).__name__}: {str(error).splitlines()[0][:160]}",
                          "the line above names the cause; also: sudo journalctl -u <service> -n 50")
                continue
            if status == 200:
                self.ok(f"{url} opens")
            else:
                self.fail(f"{url} answers {status}", "check ALLOWED_HOSTS / CSRF_TRUSTED_ORIGINS in .env")

    # ------------------------------------------------------------ logins
    def check_logins(self):
        self.head("Logins")
        if User.objects.filter(is_superuser=True, is_active=True).exists():
            self.ok("a developer (superuser) login exists for /admin/")
        else:
            self.fail("no superuser: nobody can open /admin/", "python manage.py createsuperuser")

        twins = (User.objects.exclude(email="").annotate(low=Lower("email")).values("low")
                 .annotate(n=Count("id")).filter(n__gt=1))
        for twin in twins:
            self.fail(f"{twin['n']} logins have the email {twin['low']}: none of them can sign in with it",
                      "give each login its own email (Django admin > Users)")
        if not twins:
            self.ok("every email belongs to one login only")

        for restaurant in Restaurant.objects.order_by("name"):
            label = f"{restaurant.name} ({restaurant.slug})"
            if not restaurant.is_active:
                self.ok(f"{label}: switched off (no logins expected)")
                continue
            if not restaurant.membership_active:
                self.fail(f"{label}: membership ended {restaurant.membership_end:%d %b %Y}: its logins are refused",
                          "Django admin > Restaurants > tick it > Renew membership")
            admin = restaurant.admin_login()
            if admin is None:
                self.fail(f"{label}: no restaurant admin login",
                          "Django admin > Restaurants > open it > type an Admin login password > Save")
                continue
            user = admin.user
            problems = []
            if not user.email:
                problems.append("its login has no email (staff sign in with their email)")
            if not user.has_usable_password():
                problems.append("its login has no password")
            if not (user.is_active and admin.is_active):
                problems.append("its login is switched off")
            if problems:
                self.fail(f"{label}: admin {user.email or user.username}: " + "; ".join(problems),
                          "Django admin > Restaurants > open it > set the email and an Admin login password > Save")
            else:
                staff_count = Staff.objects.filter(restaurant=restaurant).count()
                self.ok(f"{label}: admin {user.email} can sign in (tick “Sign in as restaurant admin”); "
                        f"{staff_count} login(s) in all")
