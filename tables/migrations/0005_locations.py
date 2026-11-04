"""Tables and bookings belong to a location; names and booking numbers are unique per location."""

from django.db import migrations, models
import django.db.models.deletion


def main_location_of(Location, restaurant_id, cache):
    if restaurant_id not in cache:
        cache[restaurant_id] = Location.objects.filter(restaurant_id=restaurant_id).order_by("created_at", "pk").first()
    return cache[restaurant_id]


def fill_locations(apps, schema_editor):
    Location = apps.get_model("core", "Location")
    DiningTable = apps.get_model("tables", "DiningTable")
    Booking = apps.get_model("tables", "Booking")
    cache = {}
    for table in DiningTable.objects.all():
        table.location = main_location_of(Location, table.restaurant_id, cache)
        table.save(update_fields=["location"])
    for booking in Booking.objects.select_related("table"):
        booking.location_id = booking.table.location_id if booking.table_id else main_location_of(
            Location, booking.restaurant_id, cache).pk
        booking.save(update_fields=["location"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_locations"),
        ("tables", "0004_booking_end"),
    ]

    operations = [
        migrations.AddField(
            model_name="diningtable", name="location",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="tables", to="core.location"),
        ),
        migrations.AddField(
            model_name="booking", name="location",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="bookings", to="core.location"),
        ),
        migrations.RunPython(fill_locations, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="diningtable", name="location",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="tables", to="core.location"),
        ),
        migrations.AlterField(
            model_name="booking", name="location",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="bookings", to="core.location"),
        ),
        migrations.RemoveConstraint(model_name="diningtable", name="unique_table_name_per_restaurant"),
        migrations.AddConstraint(
            model_name="diningtable",
            constraint=models.UniqueConstraint(fields=("location", "name"), name="unique_table_name_per_location"),
        ),
        migrations.RemoveConstraint(model_name="booking", name="unique_booking_no_per_restaurant"),
        migrations.AddConstraint(
            model_name="booking",
            constraint=models.UniqueConstraint(fields=("location", "booking_no"), name="unique_booking_no_per_location"),
        ),
    ]
