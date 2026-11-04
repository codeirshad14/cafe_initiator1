from django.db import migrations, models


def egg_to_non_veg(apps, schema_editor):
    """Only Veg and Non-veg are left: an egg dish becomes Non-veg."""
    MenuItem = apps.get_model("menu", "MenuItem")
    MenuItem.objects.filter(food_type="EGG").update(food_type="NON_VEG")


class Migration(migrations.Migration):

    dependencies = [
        ("menu", "0003_menuitem_ingredients_menuitem_prep_time"),
    ]

    operations = [
        migrations.RunPython(egg_to_non_veg, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="menuitem",
            name="food_type",
            field=models.CharField(choices=[("VEG", "Veg"), ("NON_VEG", "Non-veg")], default="VEG", max_length=10),
        ),
    ]
