from django.db import migrations, models
import django.db.models.deletion
import entities.models

INITIAL_TYPES = (
    'مذكرة تفاهم',
    'تعاون',
    'عقد خدمة',
    'اجتماعية',
)

LEGACY_MAP = {
    'mou': 'مذكرة تفاهم',
    'cooperation': 'تعاون',
    'service_contract': 'عقد خدمة',
    'social': 'اجتماعية',
}


def seed_and_backfill_partnership_types(apps, schema_editor):
    alias = schema_editor.connection.alias
    PartnershipType = apps.get_model('partnerships', 'PartnershipType')
    Partnership = apps.get_model('partnerships', 'Partnership')

    by_name = {}
    for raw in INITIAL_TYPES:
        name = entities.models.normalize_name(raw)
        obj, _ = PartnershipType.objects.using(alias).get_or_create(
            name_key=name.casefold(),
            defaults={'name': name, 'is_active': True},
        )
        by_name[name] = obj

    for p in Partnership.objects.using(alias).exclude(preliminary_agreement_type='').filter(partnership_type__isnull=True):
        label = LEGACY_MAP.get(p.preliminary_agreement_type)
        if label and label in by_name:
            Partnership.objects.using(alias).filter(pk=p.pk).update(partnership_type_id=by_name[label].pk)


class Migration(migrations.Migration):

    dependencies = [
        ('partnerships', '0012_willingness_details_and_teams'),
        ('regions', '0002_named_name_key_unique'),
    ]

    operations = [
        migrations.CreateModel(
            name='PartnershipType',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200, validators=[entities.models.validate_name], verbose_name='نوع الشراكة')),
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
                    models.UniqueConstraint(fields=('name_key',), name='mk_partnership_types_name_uq'),
                ],
            },
        ),
        migrations.AddField(
            model_name='partnership',
            name='partnership_type',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='partnerships', to='partnerships.partnershiptype', verbose_name='نوع الشراكة'),
        ),
        migrations.AddField(
            model_name='partnership',
            name='signing_city',
            field=models.CharField(blank=True, default='', max_length=120, verbose_name='مدينة التوقيع'),
        ),
        migrations.AddField(
            model_name='partnership',
            name='signing_region',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='signed_partnerships', to='regions.region', verbose_name='منطقة التوقيع'),
        ),
        migrations.RunPython(seed_and_backfill_partnership_types, migrations.RunPython.noop),
    ]
