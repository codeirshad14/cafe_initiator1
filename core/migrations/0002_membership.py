"""Membership like a subscription: Monthly / Yearly plan with start and end
dates, and a limit on active logins (max_users).

valid_till is renamed to membership_end. Restaurants that had no end date get
one monthly period from today, and the old FREE / BASIC / PRO plans become
MONTHLY.
"""

import django.core.validators
import django.utils.timezone
from django.db import migrations, models

import core.models


def fill_membership(apps, schema_editor):
    Restaurant = apps.get_model("core", "Restaurant")
    for restaurant in Restaurant.objects.all():
        restaurant.plan = "MONTHLY"
        if restaurant.membership_end is None:
            restaurant.membership_end = core.models.membership_end_for(restaurant.membership_start, "MONTHLY")
        restaurant.save(update_fields=["plan", "membership_end"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.RenameField("restaurant", "valid_till", "membership_end"),
        migrations.AddField(
            model_name="restaurant",
            name="membership_start",
            field=models.DateField(default=django.utils.timezone.localdate, verbose_name="membership from"),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="max_users",
            field=models.PositiveSmallIntegerField(
                default=5, validators=[django.core.validators.MinValueValidator(1)],
                verbose_name="logins allowed",
                help_text="How many staff logins may be active at once, the restaurant admin included.",
            ),
        ),
        migrations.RunPython(fill_membership, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="restaurant",
            name="membership_end",
            field=models.DateField(
                default=core.models.first_membership_end, verbose_name="membership valid till",
                help_text="Last day the staff can log in and QR menus take orders. "
                          "Use the “Renew membership” action to add one more plan period.",
            ),
        ),
        migrations.AlterField(
            model_name="restaurant",
            name="plan",
            field=models.CharField(
                choices=[("MONTHLY", "Monthly"), ("YEARLY", "Yearly")],
                default="MONTHLY", max_length=10, verbose_name="membership plan",
            ),
        ),
    ]
