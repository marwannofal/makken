from django.db import migrations


def register(apps, schema_editor):
    rules = apps.get_model('makken_mail', 'EventRule').objects.using(schema_editor.connection.alias)
    rules.get_or_create(code='account.regions_assigned', defaults={'to_subject': True, 'enabled': True})


class Migration(migrations.Migration):
    dependencies = [
        ('makken_mail', '0004_partnership_expiry_reminder'),
    ]
    operations = [migrations.RunPython(register, migrations.RunPython.noop)]
