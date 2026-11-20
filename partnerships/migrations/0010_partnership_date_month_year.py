import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('partnerships', '0009_sponsor_registration_request'),
    ]

    operations = [
        migrations.AddField(
            model_name='partnership',
            name='partnership_date',
            field=models.CharField(
                blank=True,
                default='',
                max_length=7,
                validators=[
                    django.core.validators.RegexValidator(
                        '\\A(?:[12]\\d{3}-(?:0[1-9]|1[0-2]))?\\Z',
                        'أدخل تاريخ الشراكة بصيغة الشهر والسنة (YYYY-MM).',
                    )
                ],
                verbose_name='تاريخ الشراكة',
            ),
        ),
    ]
