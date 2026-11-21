from django.db import migrations


def seed_rule(apps, schema_editor):
    EventRule = apps.get_model('makken_mail', 'EventRule')
    EventRule.objects.get_or_create(code='sponsor_request.submitted')


class Migration(migrations.Migration):

    dependencies = [
        ('makken_mail', '0009_partnership_types_events'),
    ]

    operations = [
        migrations.RunPython(seed_rule, migrations.RunPython.noop),
    ]
