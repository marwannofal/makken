from django.db import migrations, models


def remap_legacy_agreement_types(apps, schema_editor):
    Partnership = apps.get_model('partnerships', 'Partnership')
    alias = schema_editor.connection.alias
    Partnership.objects.using(alias).filter(preliminary_agreement_type='agreement_or_mou').update(
        preliminary_agreement_type='mou'
    )
    Partnership.objects.using(alias).filter(
        preliminary_agreement_type__in=['official_letter', 'signed_memo', 'signed_meeting_minutes']
    ).update(preliminary_agreement_type='other')


class Migration(migrations.Migration):

    dependencies = [
        ('partnerships', '0010_partnership_date_month_year'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='partnership',
            name='partnership_agreement_enum',
        ),
        migrations.RunPython(remap_legacy_agreement_types, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='partnership',
            name='preliminary_agreement_type',
            field=models.CharField(
                blank=True,
                choices=[
                    ('mou', 'مذكرة تفاهم'),
                    ('cooperation', 'تعاون'),
                    ('service_contract', 'عقد خدمة'),
                    ('social', 'اجتماعية'),
                    ('other', 'أخرى'),
                ],
                default='',
                editable=False,
                max_length=32,
                verbose_name='نوع الاتفاق المبدئي',
            ),
        ),
        migrations.AddConstraint(
            model_name='partnership',
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ('preliminary_agreement_type__in', ['', 'mou', 'cooperation', 'service_contract', 'social', 'other'])
                ),
                name='partnership_agreement_enum',
            ),
        ),
    ]
