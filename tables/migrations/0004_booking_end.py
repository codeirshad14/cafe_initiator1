# A booking gets an "until" (end_date, end_time): 30 minutes for a birthday,
# two days for a wedding. Bookings made before last two hours, as the floor
# assumed until now.

from datetime import datetime, timedelta

from django.db import migrations, models


def fill_until(apps, schema_editor):
    Booking = apps.get_model("tables", "Booking")
    for booking in Booking.objects.filter(models.Q(end_date__isnull=True) | models.Q(end_time__isnull=True)):
        ends = datetime.combine(booking.date, booking.time) + timedelta(hours=2)
        booking.end_date, booking.end_time = ends.date(), ends.time()
        booking.save(update_fields=["end_date", "end_time"])


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0003_booking"),
    ]

    operations = [
        migrations.AddField(
            model_name="booking",
            name="end_date",
            field=models.DateField(blank=True, null=True, verbose_name="until (day)"),
        ),
        migrations.AddField(
            model_name="booking",
            name="end_time",
            field=models.TimeField(blank=True, null=True, verbose_name="until (time)"),
        ),
        migrations.RunPython(fill_until, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="booking",
            name="end_date",
            field=models.DateField(blank=True, verbose_name="until (day)"),
        ),
        migrations.AlterField(
            model_name="booking",
            name="end_time",
            field=models.TimeField(blank=True, verbose_name="until (time)"),
        ),
    ]
