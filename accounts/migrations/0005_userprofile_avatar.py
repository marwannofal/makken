from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0004_department_kind"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="avatar",
            field=models.FileField(blank=True, default="", upload_to="avatars/", verbose_name="الصورة الشخصية"),
        ),
    ]
