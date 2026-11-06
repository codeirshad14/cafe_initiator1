"""
Django settings for the resto project (QR restaurant ordering).

Secrets and machine-specific values come from the .env file
(see .env.example) through python-decouple.
"""

from pathlib import Path

from decouple import Csv, config

BASE_DIR = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------- security
SECRET_KEY = config("SECRET_KEY")
DEBUG = config("DEBUG", default=False, cast=bool)
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="127.0.0.1,localhost", cast=Csv())
CSRF_TRUSTED_ORIGINS = config("CSRF_TRUSTED_ORIGINS", default="", cast=Csv())


# ---------------------------------------------------------------- apps
INSTALLED_APPS = [
    "jazzmin",  # the Django admin's look (JAZZMIN_SETTINGS below); must come before django.contrib.admin
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # our apps
    "core",
    "menu",
    "tables",
    "orders",
    "billing",
    "reports",
    "web",  # the public one-page website
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "resto.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                # logged-in staff, their restaurant and their sidebar links
                "core.context_processors.staff_context",
                # {{ brand_name }} ("Mr Cafe") in every template
                "core.context_processors.brand",
            ],
        },
    },
]

WSGI_APPLICATION = "resto.wsgi.application"


# ---------------------------------------------------------------- database
# Development: SQLite (USE_SQLITE=True in .env), a single db.sqlite3 file,
# nothing to install.
# Server: PostgreSQL (USE_SQLITE=False plus the DB_* values).
USE_SQLITE = config("USE_SQLITE", default=False, cast=bool)

if USE_SQLITE:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            # another file can be used for a throw-away preview: SQLITE_PATH=preview.sqlite3
            "NAME": config("SQLITE_PATH", default=str(BASE_DIR / "db.sqlite3")),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": config("DB_NAME", default="resto_db"),
            "USER": config("DB_USER", default="postgres"),
            "PASSWORD": config("DB_PASSWORD", default=""),
            "HOST": config("DB_HOST", default="localhost"),
            "PORT": config("DB_PORT", default="5432"),
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ---------------------------------------------------------------- login
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# staff log in with their email (core/auth.py); the username backend stays
# for a superuser made with createsuperuser
AUTHENTICATION_BACKENDS = [
    "core.auth.EmailBackend",
    "django.contrib.auth.backends.ModelBackend",
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "core:home"
LOGOUT_REDIRECT_URL = "login"


# ---------------------------------------------------------------- language & time
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True


# ---------------------------------------------------------------- static & media
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"  # filled by collectstatic on the server

MEDIA_URL = "/media/"
MEDIA_ROOT = config("MEDIA_ROOT", default=str(BASE_DIR / "media"))  # logos and menu item photos

# Address printed in the table QR codes, e.g. http://192.168.1.10:8000 so a
# phone on the same Wi-Fi can open it. Empty = the address you are browsing on.
SITE_URL = config("SITE_URL", default="")

# the product's name: website, login page, staff sidebar, Django admin header
BRAND_NAME = config("BRAND_NAME", default="Mr Cafe")

# shown in the website's contact section (left out when empty)
CONTACT_PHONE = config("CONTACT_PHONE", default="")
CONTACT_EMAIL = config("CONTACT_EMAIL", default="")


# ---------------------------------------------------------------- Django admin (Jazzmin)
# The developer's admin (/admin/): restaurants, memberships, logins. Jazzmin only
# changes its look; every admin class in */admin.py works as before. The page
# titles come from resto/urls.py (admin.site.site_header / site_title).
# Icons: Font Awesome 5 (free), which Jazzmin brings with it.
JAZZMIN_SETTINGS = {
    "site_brand": BRAND_NAME,
    "site_logo": "img/admin-logo.svg",
    "login_logo": "img/admin-logo.svg",
    "site_logo_classes": "",
    "site_icon": "img/admin-logo.svg",
    "welcome_sign": f"{BRAND_NAME} developer admin",
    "copyright": BRAND_NAME,
    # the search box at the top
    "search_model": ["core.Restaurant", "auth.User"],
    "user_avatar": None,
    "topmenu_links": [
        {"name": "Home", "url": "admin:index"},
        {"model": "core.Restaurant"},
        {"name": "Open the app", "url": "core:home", "new_window": True},
        {"name": "Website", "url": "web:home", "new_window": True},
    ],
    "usermenu_links": [
        {"name": "Open the app", "url": "core:home", "new_window": True, "icon": "fas fa-external-link-alt"},
    ],
    "show_sidebar": True,
    "navigation_expanded": True,
    # the apps in the order a restaurant is set up and runs
    "order_with_respect_to": [
        "core", "core.restaurant", "core.location", "core.staff",
        "menu", "tables", "orders", "billing", "web", "auth",
    ],
    "icons": {
        "auth": "fas fa-users-cog",
        "auth.user": "fas fa-user-lock",
        "auth.Group": "fas fa-users",
        "core.restaurant": "fas fa-store",
        "core.location": "fas fa-map-marker-alt",
        "core.staff": "fas fa-id-badge",
        "menu.category": "fas fa-tags",
        "menu.menuitem": "fas fa-utensils",
        "tables.diningtable": "fas fa-chair",
        "tables.booking": "fas fa-calendar-check",
        "orders.order": "fas fa-clipboard-list",
        "orders.kot": "fas fa-fire",
        "orders.notification": "fas fa-bell",
        "billing.bill": "fas fa-file-invoice",
        "billing.payment": "fas fa-rupee-sign",
        "billing.offer": "fas fa-percent",
        "web.demorequest": "fas fa-headset",
        "web.cafewebsite": "fas fa-globe",
        "web.feedback": "fas fa-comment-dots",
    },
    "default_icon_parents": "fas fa-folder",
    "default_icon_children": "fas fa-circle",
    "related_modal_active": False,
    "custom_css": "css/admin.css",
    "show_ui_builder": False,
    # the restaurant form is long: one tab per part (Restaurant, Delivery, Slider, Membership, Logins)
    "changeform_format": "single",
    "changeform_format_overrides": {"core.restaurant": "horizontal_tabs", "auth.user": "collapsible"},
    "language_chooser": False,
}

# the app's red, in Jazzmin's (AdminLTE) colour names
JAZZMIN_UI_TWEAKS = {
    "theme": "default",
    "navbar": "navbar-white navbar-light",
    "brand_colour": "navbar-danger",
    "accent": "accent-danger",
    "sidebar": "sidebar-dark-danger",
    "sidebar_nav_small_text": False,
    "sidebar_nav_flat_style": True,
    "sidebar_nav_child_indent": True,
    "navbar_fixed": True,
    "sidebar_fixed": True,
    "actions_sticky_top": True,
    "button_classes": {
        "primary": "btn-primary",
        "secondary": "btn-outline-secondary",
        "info": "btn-outline-info",
        "warning": "btn-warning",
        "danger": "btn-danger",
        "success": "btn-success",
    },
}


# ---------------------------------------------------------------- production
# Only when DEBUG=False (the server). Nginx sits in front and handles HTTPS,
# then tells Django the request was secure with X-Forwarded-Proto.
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = config("SECURE_COOKIES", default=True, cast=bool)
    CSRF_COOKIE_SECURE = config("SECURE_COOKIES", default=True, cast=bool)
    SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=False, cast=bool)  # Nginx already redirects
    SECURE_HSTS_SECONDS = config("SECURE_HSTS_SECONDS", default=0, cast=int)  # e.g. 31536000 once HTTPS works
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SECURE_REFERRER_POLICY = "same-origin"
    X_FRAME_OPTIONS = "DENY"
    # one cache for all Gunicorn workers (the login's wrong-password count, core/forms.py):
    # files in /srv/resto/cache, not each worker's own memory
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
            "LOCATION": config("CACHE_DIR", default=str(BASE_DIR / "cache")),
        }
    }
    # CSS and JS get a fingerprint in their name (app.3f9a1c.css), so after an update every
    # browser loads the new files at once, although Nginx tells them to keep them 30 days
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "resto.storage.FingerprintedStaticStorage"},
    }

# errors go to the console, so on the server they land in the Gunicorn journal
# (sudo journalctl -u resto)
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {
        "django": {"handlers": ["console"], "level": config("LOG_LEVEL", default="WARNING")},
    },
}
