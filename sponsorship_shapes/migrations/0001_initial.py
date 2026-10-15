import django.core.validators
from django.db import migrations, models
import sponsorship_shapes.models


def seed(apps, schema_editor):
    SponsorshipShape = apps.get_model("sponsorship_shapes", "SponsorshipShape")
    rows = [('رعاية مالية كاملة', 'تغطية كامل تكلفة البرنامج التدريبي من راع واحد', False, True), ('رعاية مالية جزئية', 'مساهمة الراعي بجزء من تكلفة البرنامج', False, True), ('رعاية متعددة الجهات (تحالف)', 'مشاركة أكثر من منظمة في تمويل برنامج واحد بنسب محددة', False, True), ('رعاية عينية', 'تقديم خدمات أو منتجات أو تجهيزات بدلاً من الدعم المالي', False, True), ('رعاية تدريبية', 'تحمل تكلفة التدريب أو توفير مدربين أو محتوى تدريبي', False, False), ('رعاية توظيف', 'دعم التدريب المرتبط بالتوظيف أو التدريب العملي الميداني', True, True), ('رعاية تجهيزات ومعدات', 'توفير أجهزة أو أدوات أو تجهيزات لازمة للتدريب', False, True), ('رعاية منح تدريبية', 'تمويل مقاعد تدريبية لفئات مستهدفة', False, True), ('رعاية استضافة وتنفيذ', 'توفير موقع أو منشأة لتنفيذ البرنامج', False, True), ('رعاية مشتركة (مالي + عيني)', 'دمج الدعم المالي مع دعم عيني أو خدمات', False, True)]
    for name, description, employment, active in rows:
        SponsorshipShape.objects.using(schema_editor.connection.alias).get_or_create(name_key=name.casefold(), defaults={"name": name, "description": description, "is_employment": employment, "is_active": active})



class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(name="SponsorshipShape", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("name", models.CharField(max_length=200, validators=[sponsorship_shapes.models.validate_name], verbose_name="شكل الرعاية")),
            ("description", models.TextField(blank=True, default="", max_length=2000, validators=[sponsorship_shapes.models.validate_description, django.core.validators.MaxLengthValidator(2000)], verbose_name="وصف شكل الرعاية")),
            ("is_employment", models.BooleanField(default=False, verbose_name="هل الرعاية توظيف؟")),
            ("name_key", models.CharField(editable=False, max_length=600, unique=True)),
            ("is_active", models.BooleanField(default=True, verbose_name="نشط")),
            ("version", models.PositiveBigIntegerField(default=1, editable=False)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("updated_at", models.DateTimeField(auto_now=True)),
        ], options={"ordering": ["id"], "default_permissions": ()}),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
