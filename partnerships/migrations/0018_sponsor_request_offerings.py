from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('partnerships', '0017_partnership_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='sponsorregistrationrequest',
            name='offerings',
            field=models.JSONField(blank=True, default=list, verbose_name='القطاعات والتخصصات وأشكال الرعاية'),
        ),
    ]
