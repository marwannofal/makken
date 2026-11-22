from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("market_needs", "0005_need_search_criteria"),
    ]

    operations = [
        migrations.AlterField(
            model_name="need",
            name="status",
            field=models.CharField(
                choices=[
                    ("new", "جديد"),
                    ("working", "جاري العمل (تأمين رعاة)"),
                    ("complete", "مكتملة الدعم"),
                    ("rejected", "تم الرفض"),
                ],
                db_index=True,
                default="new",
                editable=False,
                max_length=12,
            ),
        ),
    ]
