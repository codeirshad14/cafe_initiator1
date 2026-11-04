"""Bills and payments belong to a location (their order's); bill numbers count per location."""

from django.db import migrations, models
import django.db.models.deletion


def fill_locations(apps, schema_editor):
    Bill = apps.get_model("billing", "Bill")
    Payment = apps.get_model("billing", "Payment")
    for bill in Bill.objects.select_related("order"):
        bill.location_id = bill.order.location_id
        bill.save(update_fields=["location"])
    for payment in Payment.objects.select_related("bill"):
        payment.location_id = payment.bill.location_id
        payment.save(update_fields=["location"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_locations"),
        ("orders", "0005_locations"),
        ("billing", "0003_festival_offers"),
    ]

    operations = [
        migrations.AddField(
            model_name="bill", name="location",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="bills", to="core.location"),
        ),
        migrations.AddField(
            model_name="payment", name="location",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="payments", to="core.location"),
        ),
        migrations.RunPython(fill_locations, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="bill", name="location",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="bills", to="core.location"),
        ),
        migrations.AlterField(
            model_name="payment", name="location",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="payments", to="core.location"),
        ),
        migrations.RemoveConstraint(model_name="bill", name="unique_bill_no_per_restaurant"),
        migrations.AddConstraint(
            model_name="bill",
            constraint=models.UniqueConstraint(fields=("location", "bill_no"), name="unique_bill_no_per_location"),
        ),
    ]
