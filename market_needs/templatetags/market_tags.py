from decimal import Decimal, InvalidOperation
from django import template

register = template.Library()


@register.filter
def money_raw(value):
    try:
        return format(Decimal(value), ".2f")
    except (TypeError, ValueError, InvalidOperation):
        return ""


@register.filter
def sar(value):
    try:
        return format(Decimal(value), ",.2f")
    except (TypeError, ValueError, InvalidOperation):
        return "—"


@register.filter
def event_values(data):
    labels = {"allocations": "توزيع الدعم على البنود", "level": "مستوى الرعاية", "percent": "نسبة مساهمة الجهة", "matching_basis": "أساس المطابقة", "sector": "القطاع", "specialization": "التخصص", "program": "البرنامج", "program_category": "تصنيف البرنامج", "training_type": "نوع التدريب", "title": "حاجة السوق", "sector_id": "معرف القطاع", "specialization_id": "معرف التخصص", "program_id": "معرف البرنامج", "beneficiaries": "المستفيدون", "duration": "المدة", "duration_unit": "وحدة المدة", "source": "المصدر", "description": "الوصف", "observed_on": "تاريخ الرصد", "is_active": "نشط", "total_cost": "تكلفة الحاجة", "requested_support": "الدعم المطلوب", "approved_support": "الدعم المعتمد", "status": "الحالة", "regions": "المناطق", "lines": "بنود الصرف وأشكال الرعاية والمبالغ", "organization": "الجهة", "state": "حالة التطور", "entered_at": "وقت الدخول للحالة", "amount": "المساهمة", "notes": "الملاحظات", "rejection_reason": "سبب الرفض", "attachments": "المرفقات"}
    values = {"new": "جديد", "working": "جاري العمل", "complete": "مكتملة الدعم", "rejected": "رفض", "approved": "اعتماد", "capability": "قدرة", "willingness": "رغبة", "care": "رعاية", "True": "نعم", "False": "لا", "day": "يوم", "month": "شهر", "year": "سنة"}
    return [(labels.get(k, k), values.get(str(v), str(v))) for k, v in data.items()]
