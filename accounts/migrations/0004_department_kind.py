from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_department'),
    ]

    operations = [
        migrations.AddField(
            model_name='department',
            name='kind',
            field=models.CharField(
                choices=[('department', 'إدارات المؤسسة'), ('unit', 'وحدات المؤسسة')],
                default='department',
                max_length=16,
                verbose_name='نوع الإدارة',
            ),
        ),
    ]
