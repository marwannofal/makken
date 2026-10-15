from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("specializations", "0001_initial"), ("sectors", "0001_initial")]
    operations = [migrations.AddField(
        model_name="specialization", name="sector",
        field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                related_name="specializations", to="sectors.sector", verbose_name="القطاع"),
    )]
