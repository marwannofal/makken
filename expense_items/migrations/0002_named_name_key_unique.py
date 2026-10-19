"""Preserve full name-key uniqueness using an explicit named constraint."""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('expense_items', '0001_initial')]
    operations = [
        # Install the replacement before removing the implicit unique index.
        # Reverse order also restores the old index before dropping the new one.
        migrations.AddConstraint(
            model_name='expenseitem',
            constraint=models.UniqueConstraint(fields=['name_key'], name='mk_expense_items_name_uq'),
        ),
        migrations.AlterField(
            model_name='expenseitem',
            name='name_key',
            field=models.CharField(max_length=600, editable=False),
        ),
    ]
