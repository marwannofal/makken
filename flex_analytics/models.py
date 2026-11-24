"""Persistence models for المؤشرات والتحليلات المرنة (Flexible Analytics Studio)."""
from django.conf import settings
from django.contrib.auth.models import Group
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class LayoutPreset(models.TextChoices):
    COLS_1 = 'cols_1', 'عمود كامل (12)'
    COLS_2 = 'cols_2', 'عمودان متساويان (6 + 6)'
    COLS_3 = 'cols_3', 'ثلاثة أعمدة (4 + 4 + 4)'
    COLS_4 = 'cols_4', 'أربعة أعمدة (3 + 3 + 3 + 3)'
    SPLIT_1_2 = 'split_1_2', 'ثلث + ثلثان (4 + 8)'
    SPLIT_2_1 = 'split_2_1', 'ثلثان + ثلث (8 + 4)'
    SPLIT_1_3 = 'split_1_3', 'ربع + ثلاثة أرباع (3 + 9)'
    SPLIT_3_1 = 'split_3_1', 'ثلاثة أرباع + ربع (9 + 3)'
    GRID_12 = 'grid_12', 'شبكة مرنة (12 عمودًا)'


class WidgetType(models.TextChoices):
    KPI = 'kpi', 'مؤشر أداء قياسي'
    CUSTOM_KPI = 'custom_kpi', 'مؤشر أداء مخصص'
    TABLE = 'table', 'جدول مخصص'
    CHART = 'chart', 'رسم بياني'
    SUMMARY = 'summary', 'ملخص تنفيذي'


class SharePermission(models.TextChoices):
    VIEW = 'view', 'عرض فقط'
    CLONE = 'clone', 'عرض ونسخ'
    EDIT = 'edit', 'عرض وتعديل'


class FlexDashboard(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='flex_dashboards',
        verbose_name='المالك',
    )
    title = models.CharField('عنوان اللوحة', max_length=180)
    description = models.TextField('وصف اللوحة', max_length=1000, blank=True, default='')
    is_default = models.BooleanField('اللوحة الافتراضية', default=False)
    is_favorite = models.BooleanField('مفضلة', default=False)
    is_archived = models.BooleanField('مؤرشفة', default=False)
    global_filters = models.JSONField('الفلاتر العامة', default=dict, blank=True)
    theme_options = models.JSONField('خيارات العرض', default=dict, blank=True)
    version = models.PositiveBigIntegerField(default=1, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_default', '-is_favorite', '-updated_at', 'id']
        indexes = [
            models.Index(fields=['owner', 'is_archived', '-updated_at']),
            models.Index(fields=['owner', 'is_default']),
        ]
        verbose_name = 'لوحة تحليلات مرنة'
        verbose_name_plural = 'لوحات التحليلات المرنة'

    def __str__(self):
        return self.title


class FlexDashboardSection(models.Model):
    dashboard = models.ForeignKey(
        FlexDashboard,
        on_delete=models.CASCADE,
        related_name='sections',
        verbose_name='اللوحة',
    )
    title = models.CharField('عنوان القسم', max_length=180, blank=True, default='')
    description = models.CharField('وصف القسم', max_length=500, blank=True, default='')
    layout_preset = models.CharField(
        'تخطيط القسم',
        max_length=32,
        choices=LayoutPreset.choices,
        default=LayoutPreset.GRID_12,
    )
    position = models.PositiveIntegerField('الترتيب', default=0)
    is_collapsed = models.BooleanField('مطوي', default=False)
    section_filters = models.JSONField('فلاتر القسم', default=dict, blank=True)
    style_options = models.JSONField('خيارات التنسيق', default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['position', 'id']
        indexes = [
            models.Index(fields=['dashboard', 'position']),
        ]
        verbose_name = 'قسم لوحة'
        verbose_name_plural = 'أقسام اللوحة'

    def __str__(self):
        return self.title or f'قسم #{self.position + 1}'


class FlexDashboardWidget(models.Model):
    section = models.ForeignKey(
        FlexDashboardSection,
        on_delete=models.CASCADE,
        related_name='widgets',
        verbose_name='القسم',
    )
    widget_type = models.CharField(
        'نوع العنصر',
        max_length=24,
        choices=WidgetType.choices,
        default=WidgetType.KPI,
    )
    title = models.CharField('العنوان', max_length=200)
    subtitle = models.CharField('العنوان الفرعي', max_length=300, blank=True, default='')
    position = models.PositiveIntegerField('الترتيب', default=0)
    col_span = models.PositiveSmallIntegerField(
        'عرض الأعمدة',
        default=6,
        validators=[MinValueValidator(1), MaxValueValidator(12)],
    )
    row_span = models.PositiveSmallIntegerField(
        'ارتفاع الصفوف',
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(6)],
    )
    config = models.JSONField('إعدادات العنصر', default=dict, blank=True)
    is_visible = models.BooleanField('مرئي', default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['position', 'id']
        indexes = [
            models.Index(fields=['section', 'position']),
        ]
        verbose_name = 'عنصر تحليلي'
        verbose_name_plural = 'عناصر اللوحة'

    def __str__(self):
        return f'{self.title} ({self.widget_type})'


class FlexDashboardRevision(models.Model):
    dashboard = models.ForeignKey(
        FlexDashboard,
        on_delete=models.CASCADE,
        related_name='revisions',
        verbose_name='اللوحة',
    )
    version = models.PositiveBigIntegerField('الإصدار')
    label = models.CharField('وصف النسخة', max_length=200, blank=True, default='')
    snapshot = models.JSONField('لقطة اللوحة', default=dict)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-version', '-id']
        indexes = [
            models.Index(fields=['dashboard', '-version']),
        ]
        verbose_name = 'نسخة لوحة'
        verbose_name_plural = 'سجل نسخ اللوحة'


class FlexDashboardShare(models.Model):
    dashboard = models.ForeignKey(
        FlexDashboard,
        on_delete=models.CASCADE,
        related_name='shares',
        verbose_name='اللوحة',
    )
    shared_with_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='shared_flex_dashboards',
    )
    shared_with_group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='shared_flex_dashboards',
    )
    permission = models.CharField(
        'صلاحية المشاركة',
        max_length=12,
        choices=SharePermission.choices,
        default=SharePermission.VIEW,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', 'id']
        indexes = [
            models.Index(fields=['dashboard', 'shared_with_user']),
            models.Index(fields=['dashboard', 'shared_with_group']),
        ]
        verbose_name = 'مشاركة لوحة'
        verbose_name_plural = 'مشاركات اللوحة'


class FlexDashboardTemplate(models.Model):
    key = models.SlugField('المعرف', max_length=80, unique=True)
    title = models.CharField('اسم القالب', max_length=180)
    description = models.TextField('وصف القالب', max_length=1000, blank=True, default='')
    category = models.CharField('التصنيف', max_length=80, default='executive')
    is_system = models.BooleanField('قالب نظامي', default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    snapshot = models.JSONField('بنية القالب', default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_system', 'title']
        verbose_name = 'قالب لوحة'
        verbose_name_plural = 'قوالب اللوحات'

    def __str__(self):
        return self.title
