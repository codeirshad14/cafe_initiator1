"""Orders and KOTs belong to a location (their table's); order and KOT numbers count per location."""

from django.db import migrations, models
import django.db.models.deletion


def fill_locations(apps, schema_editor):
    Location = apps.get_model("core", "Location")
    Order = apps.get_model("orders", "Order")
    KOT = apps.get_model("orders", "KOT")
    main = {}
    for order in Order.objects.select_related("table"):
        if order.table_id:
            order.location_id = order.table.location_id
        else:
            if order.restaurant_id not in main:
                main[order.restaurant_id] = Location.objects.filter(
                    restaurant_id=order.restaurant_id).order_by("created_at", "pk").first().pk
            order.location_id = main[order.restaurant_id]
        order.save(update_fields=["location"])
    for kot in KOT.objects.select_related("order"):
        kot.location_id = kot.order.location_id
        kot.save(update_fields=["location"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_locations"),
        ("tables", "0005_locations"),
        ("orders", "0004_separate_bills_per_table"),
    ]

    operations = [
        migrations.AddField(
            model_name="order", name="location",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="orders", to="core.location"),
        ),
        migrations.AddField(
            model_name="kot", name="location",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="kots", to="core.location"),
        ),
        migrations.RunPython(fill_locations, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="order", name="location",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="orders", to="core.location"),
        ),
        migrations.AlterField(
            model_name="kot", name="location",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="kots", to="core.location"),
        ),
        migrations.RemoveConstraint(model_name="order", name="unique_order_no_per_restaurant"),
        migrations.AddConstraint(
            model_name="order",
            constraint=models.UniqueConstraint(fields=("location", "order_no"), name="unique_order_no_per_location"),
        ),
        migrations.RemoveConstraint(model_name="kot", name="unique_kot_no_per_restaurant"),
        migrations.AddConstraint(
            model_name="kot",
            constraint=models.UniqueConstraint(fields=("location", "kot_no"), name="unique_kot_no_per_location"),
        ),
    ]
