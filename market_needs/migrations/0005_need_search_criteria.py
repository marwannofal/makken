from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("market_needs", "0004_need_dash_need_created_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="need",
            name="search_states",
            field=models.JSONField(blank=True, default=list, verbose_name="سيتم البحث في المنظمات"),
        ),
        migrations.AddField(
            model_name="need",
            name="search_scopes",
            field=models.JSONField(blank=True, default=list, verbose_name="سيتم البحث في نطاق الكيان"),
        ),
    ]
