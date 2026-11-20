from django.db import migrations, models
import agreement_clauses.models

INITIAL_CLASSIFICATIONS = (
    'الخدمات العامة والبحوث والدراسات',
    'التدريب والتأهيل والتطوير',
    'التوظيف',
    'الشراكة المجتمعية',
)


def seed_classifications(apps, schema_editor):
    Model = apps.get_model('agreement_clauses', 'AgreementClassification')
    alias = schema_editor.connection.alias
    for raw_name in INITIAL_CLASSIFICATIONS:
        name = agreement_clauses.models.normalize_name(raw_name)
        key = name.casefold()
        Model.objects.using(alias).get_or_create(
            name_key=key,
            defaults={'name': name, 'is_active': True},
        )


class Migration(migrations.Migration):

    dependencies = [
        ('agreement_clauses', '0004_agreement_followup'),
    ]

    operations = [
        migrations.CreateModel(
            name='AgreementClassification',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200, validators=[agreement_clauses.models.validate_name], verbose_name='تصنيف الاتفاقية')),
                ('name_key', models.CharField(editable=False, max_length=600)),
                ('is_active', models.BooleanField(default=True, verbose_name='نشط')),
                ('revision', models.PositiveIntegerField(default=1, editable=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['id'],
                'default_permissions': (),
                'constraints': [
                    models.UniqueConstraint(fields=('name_key',), name='mk_agreement_classifications_name_uq'),
                ],
            },
        ),
        migrations.RunPython(seed_classifications, migrations.RunPython.noop),
    ]
