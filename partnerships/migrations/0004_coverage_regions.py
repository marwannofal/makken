from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("partnerships", "0003_willingness_support"), ("regions", "0001_initial")]
    operations = [
        migrations.CreateModel(name="PartnershipCoverageRegion", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("partnership", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="partnerships.partnership")),
            ("region", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="regions.region")),
        ], options={"db_table":"partnerships_partnership_coverage_regions", "default_permissions":(), "constraints":[models.UniqueConstraint(fields=["partnership","region"], name="partnership_coverage_unique")]}),
        migrations.AddField(model_name="partnership", name="coverage_regions", field=models.ManyToManyField(blank=True, related_name="covered_partnerships", through="partnerships.PartnershipCoverageRegion", to="regions.region", verbose_name="مناطق التغطية")),
    ]
