from django.db import migrations
from django.utils import timezone


def reformat_agreement_numbers(apps, schema_editor):
    alias = schema_editor.connection.alias
    Partnership = apps.get_model('partnerships', 'Partnership')
    for row in Partnership.objects.using(alias).filter(development_state_id='willingness').only('pk', 'created_at'):
        dt = timezone.localtime(row.created_at) if row.created_at else timezone.localtime(timezone.now())
        code = f'{dt:%Y%m}{row.pk:03d}'
        Partnership.objects.using(alias).filter(pk=row.pk).update(agreement_number=code)


class Migration(migrations.Migration):

    dependencies = [
        ('partnerships', '0014_classification_departments_hq_city'),
    ]

    operations = [
        migrations.RunPython(reformat_agreement_numbers, migrations.RunPython.noop),
    ]
