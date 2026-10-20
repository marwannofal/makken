# MAKKEN TECHNICAL DIPLOMA CATALOG v1
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("training_programs", '0003_named_name_key_unique')]
    operations = [migrations.AddField(
        model_name="trainingprogram", name="diploma_catalog",
        field=models.JSONField("بيانات دليل الدبلوم", null=True, blank=True, editable=False),
    )]
