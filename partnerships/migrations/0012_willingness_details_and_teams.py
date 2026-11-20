from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models
import django.db.models.deletion
import entities.models


def backfill_agreement_numbers(apps, schema_editor):
    alias = schema_editor.connection.alias
    Partnership = apps.get_model('partnerships', 'Partnership')
    for row in Partnership.objects.using(alias).filter(development_state_id='willingness', agreement_number__isnull=True).only('pk'):
        Partnership.objects.using(alias).filter(pk=row.pk).update(agreement_number=f'AGR-{row.pk:06d}')


class Migration(migrations.Migration):

    dependencies = [
        ('partnerships', '0011_preliminary_agreement_types'),
    ]

    operations = [
        migrations.AddField(
            model_name='partnership',
            name='agreement_number',
            field=models.CharField(blank=True, editable=False, max_length=24, null=True, unique=True, verbose_name='رقم الاتفاقية'),
        ),
        migrations.AddField(
            model_name='partnership',
            name='announcement',
            field=models.TextField(blank=True, default='', max_length=2000, verbose_name='خبر عن الشراكة'),
        ),
        migrations.AddField(
            model_name='partnership',
            name='audience',
            field=models.TextField(blank=True, default='', max_length=2000, verbose_name='الفئات المستهدفة'),
        ),
        migrations.AddField(
            model_name='partnership',
            name='duration_months',
            field=models.PositiveSmallIntegerField(blank=True, null=True, validators=[MinValueValidator(1), MaxValueValidator(600)], verbose_name='مدة الاتفاقية (بالأشهر)'),
        ),
        migrations.AddField(
            model_name='partnership',
            name='expected_results',
            field=models.TextField(blank=True, default='', max_length=2000, verbose_name='النتائج المتوقعة'),
        ),
        migrations.AddField(
            model_name='partnership',
            name='institution_rep_email',
            field=models.EmailField(blank=True, default='', max_length=254, verbose_name='البريد الإلكتروني لممثل المؤسسة'),
        ),
        migrations.AddField(
            model_name='partnership',
            name='institution_rep_name',
            field=models.CharField(blank=True, default='', max_length=160, verbose_name='اسم ممثل المؤسسة'),
        ),
        migrations.AddField(
            model_name='partnership',
            name='institution_rep_phone',
            field=models.CharField(blank=True, default='', max_length=32, verbose_name='رقم الجوال لممثل المؤسسة'),
        ),
        migrations.AddField(
            model_name='partnership',
            name='institution_signatory',
            field=models.CharField(blank=True, default='', max_length=160, verbose_name='اسم موقّع الشراكة من طرف المؤسسة'),
        ),
        migrations.AddField(
            model_name='partnership',
            name='institution_signatory_title',
            field=models.CharField(blank=True, default='', max_length=160, verbose_name='صفته الاعتبارية (المؤسسة)'),
        ),
        migrations.AddField(
            model_name='partnership',
            name='objective',
            field=models.TextField(blank=True, default='', max_length=2000, verbose_name='هدف الشراكة'),
        ),
        migrations.AddField(
            model_name='partnership',
            name='partner_rep_email',
            field=models.EmailField(blank=True, default='', max_length=254, verbose_name='البريد الإلكتروني لممثل الجهة'),
        ),
        migrations.AddField(
            model_name='partnership',
            name='partner_rep_phone',
            field=models.CharField(blank=True, default='', max_length=32, verbose_name='رقم الجوال لممثل الجهة'),
        ),
        migrations.AddField(
            model_name='partnership',
            name='partner_signatory',
            field=models.CharField(blank=True, default='', max_length=160, verbose_name='اسم موقّع الشراكة من طرف الجهة'),
        ),
        migrations.AddField(
            model_name='partnership',
            name='partner_signatory_title',
            field=models.CharField(blank=True, default='', max_length=160, verbose_name='صفته الاعتبارية (الجهة)'),
        ),
        migrations.AddField(
            model_name='partnership',
            name='renewal_rule',
            field=models.CharField(blank=True, choices=[('automatic', 'تلقائي'), ('prior_approval', 'موافقة مسبقة')], default='', max_length=16, verbose_name='نوع التجديد'),
        ),
        migrations.AddField(
            model_name='partnership',
            name='signed_on',
            field=models.DateField(blank=True, null=True, verbose_name='تاريخ التوقيع (بداية الشراكة)'),
        ),
        migrations.CreateModel(
            name='PartnershipTeamMember',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('side', models.CharField(choices=[('institution', 'فريق عمل المؤسسة'), ('partner', 'فريق عمل الجهة')], max_length=12, verbose_name='الفريق')),
                ('name', models.CharField(max_length=160, validators=[entities.models.validate_name], verbose_name='الاسم')),
                ('phone', models.CharField(blank=True, default='', max_length=32, verbose_name='الهاتف')),
                ('email', models.EmailField(blank=True, default='', max_length=254, verbose_name='البريد الإلكتروني')),
                ('organization', models.CharField(blank=True, default='', max_length=160, verbose_name='الجهة أو الإدارة')),
                ('role', models.CharField(choices=[('representative', 'ممثل'), ('lead', 'رئيس'), ('contact', 'ضابط اتصال')], max_length=16, verbose_name='الصفة')),
                ('partnership', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='team_members', to='partnerships.partnership')),
            ],
            options={
                'ordering': ['pk'],
                'default_permissions': (),
            },
        ),
        migrations.RunPython(backfill_agreement_numbers, migrations.RunPython.noop),
    ]
