from django.db import migrations, models
from django.db.models import F, Q
from django.utils import timezone


def normalize_types(apps, schema_editor):
    Program = apps.get_model("training_programs", "TrainingProgram")
    Program.objects.using(schema_editor.connection.alias).filter(
        Q(is_training=True, is_operational=True) | Q(is_training=False, is_operational=False)
    ).update(is_training=True, is_operational=False, version=F("version") + 1, updated_at=timezone.now())


class Migration(migrations.Migration):
    dependencies = [("training_programs", "0001_initial")]
    operations = [
        migrations.RunPython(normalize_types, migrations.RunPython.noop),
        migrations.RemoveConstraint(model_name="trainingprogram", name="makken_program_type_required"),
        migrations.AddConstraint(
            model_name="trainingprogram",
            constraint=models.CheckConstraint(
                condition=Q(is_training=True, is_operational=False) | Q(is_training=False, is_operational=True),
                name="makken_program_type_single",
            ),
        ),
    ]
