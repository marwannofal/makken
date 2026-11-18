from django.db import migrations


def register(apps, schema_editor):
    rules = apps.get_model('makken_mail', 'EventRule').objects.using(schema_editor.connection.alias)
    rules.get_or_create(code='partnerships.expiry_reminder', defaults={'to_employee': True})


class Migration(migrations.Migration):
    dependencies = [
        ('makken_mail', '0003_agreement_clause_events'),
        ('partnerships', '0008_partnership_term_dates'),
    ]
    operations = [migrations.RunPython(register, migrations.RunPython.noop)]
