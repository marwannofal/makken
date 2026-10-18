from django.db import migrations, models


def seed_bands(apps, schema_editor):
    Level = apps.get_model("levels", "Level")
    for key, label in [("bronze", "برونزي"), ("silver", "فضي"), ("gold", "ذهبي"), ("strategic", "استراتيجي")]:
        level = Level.objects.filter(name_key=label.casefold()).first()
        if level is None:
            level = Level.objects.create(name=label, name_key=label.casefold(), is_active=True)
        level.funding_key = key
        level.save(update_fields=["funding_key"])


class Migration(migrations.Migration):
    dependencies = [("levels", "0001_initial")]
    operations = [
        migrations.AddField(model_name="level", name="funding_key", field=models.CharField(blank=True, editable=False, max_length=16, null=True, unique=True)),
        migrations.RunPython(seed_bands, migrations.RunPython.noop),
    ]
