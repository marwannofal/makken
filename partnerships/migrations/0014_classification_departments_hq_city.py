from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_department'),
        ('agreement_clauses', '0005_agreement_classification'),
        ('partnerships', '0013_partnership_type_and_signing'),
    ]

    operations = [
        migrations.AddField(
            model_name='partnership',
            name='agreement_classification',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='partnerships',
                to='agreement_clauses.agreementclassification',
                verbose_name='تصنيف الاتفاقية',
            ),
        ),
        migrations.AddField(
            model_name='partnership',
            name='headquarters_city',
            field=models.CharField(blank=True, default='', max_length=120, verbose_name='عنوان الجهة (مدينة المقر)'),
        ),
        migrations.CreateModel(
            name='PartnershipDepartment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('department', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='accounts.department')),
                ('partnership', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='partnerships.partnership')),
            ],
            options={
                'default_permissions': (),
                'constraints': [
                    models.UniqueConstraint(fields=('partnership', 'department'), name='partnership_concerned_dept_unique'),
                ],
            },
        ),
        migrations.AddField(
            model_name='partnership',
            name='concerned_departments',
            field=models.ManyToManyField(
                blank=True,
                related_name='concerned_partnerships',
                through='partnerships.PartnershipDepartment',
                to='accounts.department',
                verbose_name='الإدارة المعنية',
            ),
        ),
    ]
