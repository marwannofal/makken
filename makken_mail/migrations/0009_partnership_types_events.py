from django.db import migrations


def register_rules(apps, schema_editor):
    alias = schema_editor.connection.alias
    rules = apps.get_model('makken_mail', 'EventRule').objects.using(alias)
    for action in ('create', 'update', 'status', 'delete', 'view', 'download', 'export_xlsx', 'export_pdf', 'denied'):
        rules.get_or_create(code=f'partnership_types.{action}')


class Migration(migrations.Migration):
    dependencies = [('makken_mail', '0008_departments_events')]
    operations = [migrations.RunPython(register_rules, migrations.RunPython.noop)]
