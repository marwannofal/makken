from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('agreement_clauses', '0006_clause_followup_notes_and_evidence'),
        ('partnerships', '0016_followup_tracking'),
    ]

    operations = [
        migrations.AddField(
            model_name='partnership',
            name='partnership_status',
            field=models.ForeignKey(
                blank=True,
                limit_choices_to={'kind': 'status'},
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='status_partnerships',
                to='agreement_clauses.agreementoption',
                verbose_name='حالة الشراكة',
            ),
        ),
    ]
