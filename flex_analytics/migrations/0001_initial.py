from django.conf import settings
import django.core.validators
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.CreateModel(
            name='FlexDashboard',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=180, verbose_name='عنوان اللوحة')),
                ('description', models.TextField(blank=True, default='', max_length=1000, verbose_name='وصف اللوحة')),
                ('is_default', models.BooleanField(default=False, verbose_name='اللوحة الافتراضية')),
                ('is_favorite', models.BooleanField(default=False, verbose_name='مفضلة')),
                ('is_archived', models.BooleanField(default=False, verbose_name='مؤرشفة')),
                ('global_filters', models.JSONField(blank=True, default=dict, verbose_name='الفلاتر العامة')),
                ('theme_options', models.JSONField(blank=True, default=dict, verbose_name='خيارات العرض')),
                ('version', models.PositiveBigIntegerField(default=1, editable=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('owner', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='flex_dashboards', to=settings.AUTH_USER_MODEL, verbose_name='المالك')),
            ],
            options={
                'verbose_name': 'لوحة تحليلات مرنة',
                'verbose_name_plural': 'لوحات التحليلات المرنة',
                'ordering': ['-is_default', '-is_favorite', '-updated_at', 'id'],
            },
        ),
        migrations.CreateModel(
            name='FlexDashboardSection',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(blank=True, default='', max_length=180, verbose_name='عنوان القسم')),
                ('description', models.CharField(blank=True, default='', max_length=500, verbose_name='وصف القسم')),
                ('layout_preset', models.CharField(choices=[('cols_1', 'عمود كامل (12)'), ('cols_2', 'عمودان متساويان (6 + 6)'), ('cols_3', 'ثلاثة أعمدة (4 + 4 + 4)'), ('cols_4', 'أربعة أعمدة (3 + 3 + 3 + 3)'), ('split_1_2', 'ثلث + ثلثان (4 + 8)'), ('split_2_1', 'ثلثان + ثلث (8 + 4)'), ('split_1_3', 'ربع + ثلاثة أرباع (3 + 9)'), ('split_3_1', 'ثلاثة أرباع + ربع (9 + 3)'), ('grid_12', 'شبكة مرنة (12 عمودًا)')], default='grid_12', max_length=32, verbose_name='تخطيط القسم')),
                ('position', models.PositiveIntegerField(default=0, verbose_name='الترتيب')),
                ('is_collapsed', models.BooleanField(default=False, verbose_name='مطوي')),
                ('section_filters', models.JSONField(blank=True, default=dict, verbose_name='فلاتر القسم')),
                ('style_options', models.JSONField(blank=True, default=dict, verbose_name='خيارات التنسيق')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('dashboard', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='sections', to='flex_analytics.flexdashboard', verbose_name='اللوحة')),
            ],
            options={
                'verbose_name': 'قسم لوحة',
                'verbose_name_plural': 'أقسام اللوحة',
                'ordering': ['position', 'id'],
            },
        ),
        migrations.CreateModel(
            name='FlexDashboardTemplate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.SlugField(max_length=80, unique=True, verbose_name='المعرف')),
                ('title', models.CharField(max_length=180, verbose_name='اسم القالب')),
                ('description', models.TextField(blank=True, default='', max_length=1000, verbose_name='وصف القالب')),
                ('category', models.CharField(default='executive', max_length=80, verbose_name='التصنيف')),
                ('is_system', models.BooleanField(default=False, verbose_name='قالب نظامي')),
                ('snapshot', models.JSONField(default=dict, verbose_name='بنية القالب')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'قالب لوحة',
                'verbose_name_plural': 'قوالب اللوحات',
                'ordering': ['-is_system', 'title'],
            },
        ),
        migrations.CreateModel(
            name='FlexDashboardWidget',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('widget_type', models.CharField(choices=[('kpi', 'مؤشر أداء قياسي'), ('custom_kpi', 'مؤشر أداء مخصص'), ('table', 'جدول مخصص'), ('chart', 'رسم بياني'), ('summary', 'ملخص تنفيذي')], default='kpi', max_length=24, verbose_name='نوع العنصر')),
                ('title', models.CharField(max_length=200, verbose_name='العنوان')),
                ('subtitle', models.CharField(blank=True, default='', max_length=300, verbose_name='العنوان الفرعي')),
                ('position', models.PositiveIntegerField(default=0, verbose_name='الترتيب')),
                ('col_span', models.PositiveSmallIntegerField(default=6, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(12)], verbose_name='عرض الأعمدة')),
                ('row_span', models.PositiveSmallIntegerField(default=1, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(6)], verbose_name='ارتفاع الصفوف')),
                ('config', models.JSONField(blank=True, default=dict, verbose_name='إعدادات العنصر')),
                ('is_visible', models.BooleanField(default=True, verbose_name='مرئي')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('section', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='widgets', to='flex_analytics.flexdashboardsection', verbose_name='القسم')),
            ],
            options={
                'verbose_name': 'عنصر تحليلي',
                'verbose_name_plural': 'عناصر اللوحة',
                'ordering': ['position', 'id'],
            },
        ),
        migrations.CreateModel(
            name='FlexDashboardShare',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('permission', models.CharField(choices=[('view', 'عرض فقط'), ('clone', 'عرض ونسخ'), ('edit', 'عرض وتعديل')], default='view', max_length=12, verbose_name='صلاحية المشاركة')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('dashboard', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='shares', to='flex_analytics.flexdashboard', verbose_name='اللوحة')),
                ('shared_with_group', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='shared_flex_dashboards', to='auth.group')),
                ('shared_with_user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='shared_flex_dashboards', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'مشاركة لوحة',
                'verbose_name_plural': 'مشاركات اللوحة',
                'ordering': ['-created_at', 'id'],
            },
        ),
        migrations.CreateModel(
            name='FlexDashboardRevision',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('version', models.PositiveBigIntegerField(verbose_name='الإصدار')),
                ('label', models.CharField(blank=True, default='', max_length=200, verbose_name='وصف النسخة')),
                ('snapshot', models.JSONField(default=dict, verbose_name='لقطة اللوحة')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('dashboard', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='revisions', to='flex_analytics.flexdashboard', verbose_name='اللوحة')),
            ],
            options={
                'verbose_name': 'نسخة لوحة',
                'verbose_name_plural': 'سجل نسخ اللوحة',
                'ordering': ['-version', '-id'],
            },
        ),
        migrations.AddIndex(
            model_name='flexdashboard',
            index=models.Index(fields=['owner', 'is_archived', '-updated_at'], name='flex_analyt_owner_i_6b0c7e_idx'),
        ),
        migrations.AddIndex(
            model_name='flexdashboard',
            index=models.Index(fields=['owner', 'is_default'], name='flex_analyt_owner_i_4f41d2_idx'),
        ),
        migrations.AddIndex(
            model_name='flexdashboardsection',
            index=models.Index(fields=['dashboard', 'position'], name='flex_analyt_dashboa_032e3c_idx'),
        ),
        migrations.AddIndex(
            model_name='flexdashboardwidget',
            index=models.Index(fields=['section', 'position'], name='flex_analyt_section_081e40_idx'),
        ),
        migrations.AddIndex(
            model_name='flexdashboardrevision',
            index=models.Index(fields=['dashboard', '-version'], name='flex_analyt_dashboa_15a781_idx'),
        ),
        migrations.AddIndex(
            model_name='flexdashboardshare',
            index=models.Index(fields=['dashboard', 'shared_with_user'], name='flex_analyt_dashboa_a890f1_idx'),
        ),
        migrations.AddIndex(
            model_name='flexdashboardshare',
            index=models.Index(fields=['dashboard', 'shared_with_group'], name='flex_analyt_dashboa_d7f042_idx'),
        ),
    ]
