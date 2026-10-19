"""Preserve full name-key uniqueness using an explicit named constraint."""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('levels', '0002_funding_key')]
    operations = [
        # Install the replacement before removing the implicit unique index.
        # Reverse order also restores the old index before dropping the new one.
        migrations.AddConstraint(
            model_name='level',
            constraint=models.UniqueConstraint(fields=['name_key'], name='mk_levels_name_uq'),
        ),
        migrations.AlterField(
            model_name='level',
            name='name_key',
            field=models.CharField(max_length=300, editable=False),
        ),
    ]
