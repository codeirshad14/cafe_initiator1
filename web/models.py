from django.db import models


class DemoRequest(models.Model):
    """A restaurant owner asking for a demo from the public website.

    Not restaurant data: these are leads for the platform owner, read in the
    Django admin.
    """

    name = models.CharField("your name", max_length=100)
    restaurant_name = models.CharField("restaurant name", max_length=150)
    phone = models.CharField("mobile number", max_length=15)
    city = models.CharField(max_length=80, blank=True)
    tables = models.PositiveSmallIntegerField("number of tables", null=True, blank=True)
    message = models.TextField(blank=True)
    is_contacted = models.BooleanField("contacted", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.restaurant_name} ({self.name})"
