from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "Restaurants & staff"

    def ready(self):
        from .live import watch_changes
        watch_changes()  # live screens: see core/live.py
