"""Authoritative execution writes: permissions, locks, eligibility and audit."""
import hashlib
import json
import uuid
from django.db import transaction
from django.db.models import Sum, prefetch_related_objects
from django.utils import timezone
from access_control.policy import require
from partnerships.models import Partnership, PartnershipOffering
from regions.models import Region
from sectors.models import Sector
from specializations.models import Specialization
from sponsorship_shapes.models import SponsorshipShape
from service_providers.models import ServiceProvider, ProviderCoverage
from training_programs.models import TrainingProgram
from .models import Need, NeedExecution, ExecutionProvider, ExecutionEmployer, ExecutionStatus, AuditEvent, SponsorshipStatus
from . import execution_matching as matching


class ExecutionConflict(Exception):
    pass


def snapshot(execution):
    if not execution:
        return {}
    return {"حالة التنفيذ": execution.get_status_display(), "الإصدار": execution.version,
            "ملاحظات التنفيذ": execution.notes,
            "مزودو التدريب": [row.evidence for row in execution.provider_links.all()],
            "جهات التوظيف": [row.evidence for row in execution.employer_links.all()],
            "تاريخ اكتمال التنفيذ": execution.completed_at.isoformat() if execution.completed_at else None}


def validate_selection(need, status, provider_ids, employer_ids, old_providers=(), old_employers=()):
    if status not in ExecutionStatus.values:
        raise ExecutionConflict("اختر حالة تنفيذ صحيحة.")
    for ids in (provider_ids, employer_ids):
        if len(ids) > 200 or len(ids) != len(set(ids)) or any(type(i) is not int or i <= 0 for i in ids):
            raise ExecutionConflict("اختيارات الجهات غير صحيحة أو مكررة؛ الحد الأقصى 200 لكل قائمة.")
    valid_providers = {p.pk: p for p in matching.providers(need).filter(pk__in=provider_ids)}
    valid_employers = {p.pk: p for p in matching.employers(need).filter(pk__in=employer_ids)}
    invalid_p = set(provider_ids) - valid_providers.keys()
    invalid_e = set(employer_ids) - valid_employers.keys()
    # A new draft may preserve already saved historical references, clearly marked.
    if status == ExecutionStatus.NEW:
        invalid_p -= set(old_providers)
        invalid_e -= set(old_employers)
    if invalid_p or invalid_e:
        raise ExecutionConflict("تغيّرت أهلية جهة مختارة، أو لم تعد نشطة أو مطابقة. راجع الاختيارات قبل المتابعة؛ يمكن حفظ المراجع السابقة كمسودة جديد فقط.")
    if need.training_type == "تدريبي" and employer_ids:
        raise ExecutionConflict("البرنامج التدريبي لا يقبل اختيار جهات توظيف.")
    if status != ExecutionStatus.NEW:
        if not provider_ids:
            raise ExecutionConflict("اختر مزود تدريب مطابقًا واحدًا على الأقل لبدء التنفيذ أو إكماله.")
        if need.training_type == "تشغيلي" and not employer_ids:
            raise ExecutionConflict("البرنامج التشغيلي يحتاج جهة توظيف مطابقة واحدة على الأقل، إضافةً إلى مزود التدريب.")
        if ("تدريبي" if need.program.is_training else "تشغيلي") != need.training_type:
            raise ExecutionConflict("نوع البرنامج المرجعي تغير عن النسخة المعتمدة للبطاقة؛ راجع المسؤول قبل التنفيذ.")
    return valid_providers, valid_employers


def save_execution(*, need_id, expected_version, expected_need_version, nonce, data, actor):
    require(actor, "provider_assignments", "view")
    status = data["status"]
    provider_ids, employer_ids = sorted(data["providers"]), sorted(data["employers"])
    notes = data.get("notes", "").strip()
    if len(notes) > 4000:
        raise ExecutionConflict("الحد الأقصى لملاحظات التنفيذ 4000 حرف.")
    digest = hashlib.sha256(json.dumps({"status": status, "providers": provider_ids, "employers": employer_ids, "notes": notes}, sort_keys=True).encode()).hexdigest()
    try:
        nonce = uuid.UUID(str(nonce))
    except (ValueError, TypeError, AttributeError):
        raise ExecutionConflict("تعذّر التحقق من الطلب. حدّث الصفحة.")
    with transaction.atomic():
        need = Need.objects.select_for_update().get(pk=need_id)
        execution = NeedExecution.objects.select_for_update().filter(need=need).first()
        require(actor, "provider_assignments", "edit" if execution else "create")
        previous_status = execution.status if execution else ExecutionStatus.NEW
        if status != previous_status:
            require(actor, "provider_assignments", "change_status")
        if execution and execution.last_request == nonce:
            if execution.last_digest != digest or execution.updated_by_id != actor.pk:
                raise ExecutionConflict("أعيد استخدام الطلب بمحتوى مختلف. حدّث الصفحة.")
            return execution
        if execution and execution.status == ExecutionStatus.COMPLETE:
            raise ExecutionConflict("اكتمل تنفيذ هذه البطاقة، ولا يمكن تعديل بيانات التنفيذ أو الجهات المرتبطة بها.")
        if (execution.version if execution else 0) != expected_version or need.version != expected_need_version:
            raise ExecutionConflict("حُفظ تعديل أحدث أثناء عملك. حدّث الصفحة وراجع البيانات قبل الحفظ.")
        total = need.sponsorships.filter(status=SponsorshipStatus.APPROVED).aggregate(value=Sum("amount"))["value"] or 0
        if not need.is_active or need.status != "complete" or total != need.total_cost or need.approved_support != total:
            raise ExecutionConflict("لا يمكن إعداد التنفيذ إلا لبطاقة نشطة مكتملة الدعم فعليًا بنسبة 100٪.")
        list(ServiceProvider.objects.select_for_update().filter(pk__in=provider_ids).order_by("pk"))
        list(Partnership.objects.select_for_update().filter(pk__in=employer_ids).order_by("pk"))
        need.program = TrainingProgram.objects.select_for_update().get(pk=need.program_id)
        # Follow the provider writer's reference order: program, regions,
        # sector, specialization. Parent provider/organization locks precede it.
        region_ids = list(need.regions.values_list("pk", flat=True))
        list(Region.objects.select_for_update().filter(pk__in=region_ids).order_by("pk"))
        need.sector = Sector.objects.select_for_update().get(pk=need.sector_id)
        need.specialization = Specialization.objects.select_for_update().get(pk=need.specialization_id)
        list(ProviderCoverage.objects.select_for_update().filter(provider_id__in=provider_ids).order_by("pk"))
        offerings = list(PartnershipOffering.objects.select_for_update().filter(partnership_id__in=employer_ids).order_by("pk"))
        list(SponsorshipShape.objects.select_for_update().filter(pk__in={o.sponsorship_shape_id for o in offerings}).order_by("pk"))
        old_p = {row.provider_id: row for row in execution.provider_links.all()} if execution else {}
        old_e = {row.partnership_id: row for row in execution.employer_links.all()} if execution else {}
        prefetch_related_objects([need], "regions")
        valid_p, valid_e = validate_selection(need, status, provider_ids, employer_ids, old_p, old_e)
        before = snapshot(execution)
        if not execution:
            execution = NeedExecution(need=need, created_by=actor)
        else:
            execution.version += 1
        execution.status, execution.notes = status, notes
        execution.updated_by, execution.last_request, execution.last_digest = actor, nonce, digest
        execution.completed_at = timezone.now() if status == ExecutionStatus.COMPLETE else None
        execution.save()
        execution.provider_links.exclude(provider_id__in=provider_ids).delete()
        execution.employer_links.exclude(partnership_id__in=employer_ids).delete()
        for pk in provider_ids:
            evidence = matching.provider_evidence(need, valid_p[pk]) if pk in valid_p else old_p[pk].evidence
            ExecutionProvider.objects.update_or_create(execution=execution, provider_id=pk, defaults={"evidence": evidence})
        for pk in employer_ids:
            evidence = matching.employer_evidence(need, valid_e[pk]) if pk in valid_e else old_e[pk].evidence
            ExecutionEmployer.objects.update_or_create(execution=execution, partnership_id=pk, defaults={"evidence": evidence})
        AuditEvent.objects.create(need=need, need_number=need.number, actor=actor, action="تنفيذ البرنامج · حفظ واختيار المزودين", before=before, after=snapshot(execution))
        return execution
