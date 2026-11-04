"""Locations (outlets): every company gets its "Main" location; staff are mapped to locations; two new roles."""

from django.db import migrations, models
import django.db.models.deletion


def make_main_locations(apps, schema_editor):
    Restaurant = apps.get_model("core", "Restaurant")
    Location = apps.get_model("core", "Location")
    for restaurant in Restaurant.objects.all():
        if not Location.objects.filter(restaurant=restaurant).exists():
            Location.objects.create(restaurant=restaurant, name="Main", address=restaurant.address, phone=restaurant.phone)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0007_live_version"),
    ]

    operations = [
        migrations.CreateModel(
            name="Location",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100, verbose_name="location name")),
                ("address", models.TextField(blank=True)),
                ("phone", models.CharField(blank=True, max_length=20)),
                ("is_active", models.BooleanField(default=True, verbose_name="open")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("restaurant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="locations", to="core.restaurant")),
            ],
            options={"ordering": ["created_at", "pk"]},
        ),
        migrations.AddConstraint(
            model_name="location",
            constraint=models.UniqueConstraint(fields=("restaurant", "name"), name="unique_location_name_per_restaurant"),
        ),
        migrations.AlterField(
            model_name="staff",
            name="role",
            field=models.CharField(choices=[
                ("ADMIN", "Admin"), ("MANAGER", "Manager"), ("RM", "Restaurant manager"), ("ALL", "All-rounder"),
                ("CASHIER", "Cashier (bills)"), ("KITCHEN", "Kitchen"), ("WAITER", "Waiter"), ("RIDER", "Rider"),
            ], max_length=10),
        ),
        migrations.AddField(
            model_name="staff",
            name="locations",
            field=models.ManyToManyField(blank=True, related_name="staff_members", to="core.location"),
        ),
        migrations.RunPython(make_main_locations, migrations.RunPython.noop),
    ]
