"""Preserve full name-key uniqueness using an explicit named constraint."""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('training_programs', '0002_single_training_type')]
    operations = [
        # Install the replacement before removing the implicit unique index.
        # Reverse order also restores the old index before dropping the new one.
        migrations.AddConstraint(
            model_name='trainingprogram',
            constraint=models.UniqueConstraint(fields=['name_key'], name='mk_training_programs_name_uq'),
        ),
        migrations.AlterField(
            model_name='trainingprogram',
            name='name_key',
            field=models.CharField(max_length=600, editable=False),
        ),
    ]
