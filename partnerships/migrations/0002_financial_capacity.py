from django.core.validators import MinValueValidator
from django.db import migrations, models
from decimal import Decimal


class Migration(migrations.Migration):
    dependencies = [('partnerships', '0001_initial')]
    operations = [
        migrations.AddField(
            model_name='partnership', name='financial_capacity',
            field=models.DecimalField('القدرة المالية', max_digits=14, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal('0'))]),
        ),
        migrations.AddConstraint(
            model_name='partnership',
            constraint=models.CheckConstraint(condition=models.Q(financial_capacity__isnull=True) | models.Q(financial_capacity__gte=0), name='partnership_financial_nonnegative'),
        ),
    ]
