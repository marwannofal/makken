from django.db import migrations

OPTIONS = {
    'entity': ('حكومي', 'خاص', 'شبه حكومي', 'أخرى'),
    'status': ('مستمرة', 'منتهية', 'معلقة', 'متعثرة'),
    'partnership_type': ('مذكرة تفاهم', 'تعاون', 'عقد خدمة', 'شراكة اجتماعية', 'أخرى'),
    'classification': ('الخدمات العامة والبحوث والدراسات', 'التدريب والتأهيل والتطوير', 'التوظيف', 'الشراكة المجتمعية'),
    'city': ('الرياض', 'جدة', 'مكة المكرمة', 'المدينة المنورة', 'الدمام', 'بريدة', 'أبها', 'تبوك',
             'حائل', 'عرعر', 'جازان', 'نجران', 'الباحة', 'سكاكا'),
}

DEPARTMENTS = (('الكليات', 'unit'), ('المعاهد', 'unit'), ('الإدارة العامة للتشاركية', 'department'))


def seed(apps, schema_editor):
    options = apps.get_model('agreement_clauses', 'AgreementOption').objects.using(schema_editor.connection.alias)
    for kind, names in OPTIONS.items():
        for name in names:
            options.get_or_create(kind=kind, name=name)
    for name, subtype in DEPARTMENTS:
        options.get_or_create(kind='department', name=name, defaults={'department_type': subtype})


class Migration(migrations.Migration):
    dependencies = [('agreement_clauses', '0002_agreement_internal_record')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
