from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('partnerships', '0015_agreement_number_yyyymm_format'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='partnership',
            name='followup_updated_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='تاريخ آخر تحديث للمتابعة'),
        ),
        migrations.AddField(
            model_name='partnership',
            name='followup_updated_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='آخر تحديث للمتابعة بواسطة'),
        ),
    ]
