from django.db import migrations, models
import django.db.models.deletion
import expense_items.models

DEFAULT_DEPARTMENTS = (
    'الإدارة العامة للتشاركية',
    'الكليات',
    'المعاهد',
)


def seed_and_migrate_departments(apps, schema_editor):
    alias = schema_editor.connection.alias
    Department = apps.get_model('accounts', 'Department')
    UserProfile = apps.get_model('accounts', 'UserProfile')
    AgreementOption = apps.get_model('agreement_clauses', 'AgreementOption')

    by_key = {}

    def ensure_department(raw_name, is_active=True):
        name = expense_items.models.normalize_name(raw_name)
        key = name.casefold()
        if key in by_key:
            return by_key[key]
        dept, _ = Department.objects.using(alias).get_or_create(
            name_key=key,
            defaults={'name': name, 'is_active': is_active},
        )
        by_key[key] = dept
        return dept

    for opt in AgreementOption.objects.using(alias).filter(kind='department').order_by('id'):
        ensure_department(opt.name, is_active=opt.is_active)

    for raw_name in DEFAULT_DEPARTMENTS:
        ensure_department(raw_name, is_active=True)

    for profile in UserProfile.objects.using(alias).exclude(department_id__isnull=True).select_related('department'):
        old_opt = profile.department
        if old_opt is not None:
            dept = ensure_department(old_opt.name, is_active=old_opt.is_active)
            UserProfile.objects.using(alias).filter(pk=profile.pk).update(department_ref_id=dept.pk)


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_employee_profile_and_password_policy'),
        ('agreement_clauses', '0003_seed_agreement_options'),
    ]

    operations = [
        migrations.CreateModel(
            name='Department',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200, validators=[expense_items.models.validate_name], verbose_name='اسم الإدارة أو الوحدة')),
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
                    models.UniqueConstraint(fields=('name_key',), name='mk_departments_name_uq'),
                ],
            },
        ),
        migrations.AddField(
            model_name='userprofile',
            name='department_ref',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='+',
                to='accounts.department',
                verbose_name='الإدارة أو الوحدة',
            ),
        ),
        migrations.RunPython(seed_and_migrate_departments, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='userprofile',
            name='department',
        ),
        migrations.RenameField(
            model_name='userprofile',
            old_name='department_ref',
            new_name='department',
        ),
    ]
