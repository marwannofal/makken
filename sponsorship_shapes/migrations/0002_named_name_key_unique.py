"""Preserve full name-key uniqueness using an explicit named constraint."""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('sponsorship_shapes', '0001_initial')]
    operations = [
        # Install the replacement before removing the implicit unique index.
        # Reverse order also restores the old index before dropping the new one.
        migrations.AddConstraint(
            model_name='sponsorshipshape',
            constraint=models.UniqueConstraint(fields=['name_key'], name='mk_sponsorship_shapes_name_uq'),
        ),
        migrations.AlterField(
            model_name='sponsorshipshape',
            name='name_key',
            field=models.CharField(max_length=600, editable=False),
        ),
    ]
