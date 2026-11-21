from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('agreement_clauses', '0005_agreement_classification'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='clauseassignment',
            name='notes',
            field=models.TextField(blank=True, default='', verbose_name='ملاحظات البند'),
        ),
        migrations.CreateModel(
            name='ClauseEvidence',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file', models.CharField(max_length=255)),
                ('original_name', models.CharField(max_length=255)),
                ('size', models.PositiveBigIntegerField()),
                ('content_type', models.CharField(max_length=40)),
                ('uploaded_at', models.DateTimeField(auto_now_add=True)),
                ('assignment', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='evidences', to='agreement_clauses.clauseassignment')),
                ('uploaded_by', models.ForeignKey(editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-uploaded_at', '-id'],
                'default_permissions': (),
            },
        ),
    ]
