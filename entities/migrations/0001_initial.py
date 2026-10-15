from django.db import migrations, models
import entities.models


def seed(apps, schema_editor):
    Entity = apps.get_model("entities", "Entity")
    # The reference has no name column: use its type/branch labels as editable names.
    rows = [
        ("حكومي", "government", ""),
        ("خاص كبير", "non_government", "private_large"),
        ("خاص صغير ومتوسط", "non_government", "private_sme"),
        ("غير ربحي مهني", "non_government", "nonprofit_professional"),
        ("غير ربحي مجتمعي", "non_government", "nonprofit_community"),
    ]
    for name, kind, branch in rows:
        Entity.objects.using(schema_editor.connection.alias).get_or_create(name_key=name, defaults={"name": name, "entity_type": kind, "branch": branch, "is_active": True})


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(name="Entity", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("name", models.CharField(max_length=200, validators=[entities.models.validate_name], verbose_name="اسم الكيان")),
            ("name_key", models.CharField(editable=False, max_length=600, unique=True)),
            ("entity_type", models.CharField(choices=[("government", "حكومي"), ("non_government", "غير حكومي")], max_length=20, verbose_name="الكيان")),
            ("branch", models.CharField(blank=True, choices=[("private_large", "خاص كبير"), ("private_sme", "خاص صغير ومتوسط"), ("nonprofit_professional", "غير ربحي مهني"), ("nonprofit_community", "غير ربحي مجتمعي")], default="", max_length=32, verbose_name="فرع الكيان")),
            ("is_active", models.BooleanField(default=True, verbose_name="نشط")),
            ("version", models.PositiveBigIntegerField(default=1, editable=False)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("updated_at", models.DateTimeField(auto_now=True)),
        ], options={"ordering": ["id"], "default_permissions": (), "constraints": [
            models.CheckConstraint(condition=models.Q(entity_type__in=["government", "non_government"]), name="entity_type_fixed_enum"),
            models.CheckConstraint(condition=models.Q(entity_type="government", branch="") | models.Q(entity_type="non_government", branch__in=["private_large", "private_sme", "nonprofit_professional", "nonprofit_community"]), name="entity_branch_matches_type"),
        ]}),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
