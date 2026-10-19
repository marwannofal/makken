"""All mutations serialize on the need row, then sponsorship, then organization.

On MySQL/InnoDB SELECT FOR UPDATE provides cross-worker serialization. SQLite
is suitable for local UI tests only; run the concurrency suite on MySQL.
"""

from core.dependencies import DependencyBlocked, ensure_allowed, blocked_context
# MAKKEN LINKED RECORD PROTECTION v1
import uuid
from decimal import Decimal
from pathlib import Path
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from partnerships.attachment_storage import willingness_storage, delete_private_files
from partnerships.willingness import safe_filename
from partnerships.models import Partnership, DevelopmentHistory
from care_states.models import DevelopmentState, StateColor
from .forms import NeedForm, FollowupForm
from .matching import candidates, eligible_for_approval
from .models import Need, ExpenseLine, Sponsorship, SponsorshipStatus, NeedStatus, AuditEvent, SupportAttachment, SponsorshipAllocation


class Conflict(Exception):
    pass


class InvalidForm(Exception):
    def __init__(self, form):
        self.form = form


def audit(need, actor, action, before=None, after=None, sponsorship=None):
    return AuditEvent.objects.create(need=need, need_number=need.number, actor=actor, action=action, before=before or {}, after=after or {}, sponsorship=sponsorship)


def card_data(need):
    return {**{name: str(getattr(need, name)) for name in ("title", "beneficiaries", "duration", "duration_unit", "source", "description", "observed_on", "is_active", "total_cost", "requested_support", "status", "approved_support")},
            "sector": need.sector.name, "specialization": need.specialization.name,
            "program": need.program_name, "program_category": need.program_category, "training_type": need.training_type,
            "regions": "، ".join(need.regions.values_list("name", flat=True)),
            "lines": "\n".join(f"{line.expense_item.name} / {line.sponsorship_shape.name}: {line.amount}" for line in need.expense_lines.select_related("expense_item", "sponsorship_shape"))}


def sponsor_data(record):
    return {"organization": record.partnership.name, "status": record.status, "amount": str(record.amount), "notes": record.notes, "rejection_reason": record.rejection_reason,
            "percent": str(record.percent), "level": record.level_name,
            "allocations": "\n".join(f"{row.expense_line.expense_item.name}: {row.amount}" for row in record.allocations.select_related("expense_line__expense_item"))}


def lock_need(pk, version):
    need = Need.objects.select_for_update().filter(pk=pk).first()
    if not need or need.version != version:
        raise Conflict("تغيّرت البطاقة أو نُفذ الطلب مسبقًا. حدّث الصفحة وراجع أحدث البيانات.")
    return need


@transaction.atomic
def save_need(data, actor, pk=None, version=None, nonce=None):
    need = lock_need(pk, version) if pk else None
    if not pk and nonce and Need.objects.filter(request_key=nonce).exists():
        raise Conflict("تم حفظ هذا الطلب مسبقًا. افتح قائمة البطاقات.")
    # Lock selected references in a stable order. Existing reference CRUD also
    # locks these rows, so validation and persistence observe one reference set.
    from sectors.models import Sector
    from specializations.models import Specialization
    from training_programs.models import TrainingProgram
    from regions.models import Region
    from expense_items.models import ExpenseItem
    from sponsorship_shapes.models import SponsorshipShape
    for model in (Sector, Specialization, TrainingProgram, Region, ExpenseItem, SponsorshipShape):
        # Small reference catalogs; locking only references avoids locking peers.
        if model in (Sector, Specialization, TrainingProgram):
            key = {Sector: "sector", Specialization: "specialization", TrainingProgram: "program"}[model]
            raw = str(data.get(key, ""))
            ids = [int(raw)] if raw.isascii() and raw.isdigit() else []
        elif model is Region:
            raw = data.getlist("regions") if hasattr(data, "getlist") else data.get("regions", [])
            ids = [int(x) for x in raw if str(x).isascii() and str(x).isdigit()]
        else:
            import json
            try:
                rows = json.loads(data.get("lines", "[]"))
                ids = [r.get("expense" if model is ExpenseItem else "shape") for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
                ids = [x for x in ids if type(x) is int]
            except (ValueError, TypeError):
                ids = []
        list(model.objects.select_for_update().filter(pk__in=ids).order_by("pk"))
    form = NeedForm(data, instance=need)
    if not form.is_valid():
        raise InvalidForm(form)
    clean = form.cleaned_data
    ensure_allowed(need, "edit", clean["is_active"] == "1")
    before = card_data(need) if need else {}
    if need and need.sponsorships.filter(status=SponsorshipStatus.APPROVED).exists():
        protected = ("sector", "specialization", "program", "beneficiaries", "requested_support")
        changed = any(getattr(need, name + "_id" if name in ("sector", "specialization", "program") else name) != (clean[name].pk if name in ("sector", "specialization", "program") else clean[name]) for name in protected)
        old_lines = sorted((x.expense_item_id, x.sponsorship_shape_id, x.amount) for x in need.expense_lines.all())
        new_lines = sorted((x["expense"], x["shape"], x["amount"]) for x in clean["lines"])
        if changed or old_lines != new_lines or set(need.regions.values_list("pk", flat=True)) != {r.pk for r in clean["regions"]}:
            raise Conflict("توجد مساهمات معتمدة؛ لا يمكن تغيير البرنامج أو القطاع أو التخصص أو المناطق أو المستفيدين أو البنود أو الأساس المالي. يمكن تعديل البيانات الوصفية وحالة التفعيل.")
    new = need is None
    if new:
        need = Need(created_by=actor, request_key=nonce or uuid.uuid4())
    for field in ("title", "sector", "specialization", "description", "duration", "duration_unit", "source", "beneficiaries", "program", "requested_support", "observed_on"):
        setattr(need, field, clean[field])
    if new or not need.sponsorships.filter(status=SponsorshipStatus.APPROVED).exists():
        need.program_name = clean["program"].name
        need.program_category = clean["program"].get_category_display()
        need.training_type = "تدريبي" if clean["program"].is_training else "تشغيلي"
    need.total_cost = clean["total_cost"]
    need.is_active = clean["is_active"] == "1"
    if not new:
        need.version += 1
    need.save()
    need.regions.set(clean["regions"])
    # Keep funded line identities: approved allocations reference these rows.
    if not need.sponsorships.filter(status=SponsorshipStatus.APPROVED).exists():
        need.expense_lines.all().delete()
        ExpenseLine.objects.bulk_create([ExpenseLine(need=need, expense_item_id=line["expense"], sponsorship_shape_id=line["shape"], amount=line["amount"], position=i) for i, line in enumerate(clean["lines"])])
    audit(need, actor, "إنشاء البطاقة" if new else "تعديل البطاقة", before, card_data(need))
    return need


def recompute(need, actor):
    old = {"status": need.status, "approved_support": str(need.approved_support)}
    approved = need.sponsorships.filter(status=SponsorshipStatus.APPROVED).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    if approved > need.total_cost:
        raise Conflict("إجمالي الدعم يتجاوز تكلفة الحاجة.")
    need.approved_support = approved
    if approved == need.total_cost:
        need.status = NeedStatus.COMPLETE
    elif approved > 0 or need.sponsorships.filter(status=SponsorshipStatus.NEW).exists():
        need.status = NeedStatus.WORKING
    elif need.sponsorships.exists():
        need.status = NeedStatus.REJECTED
    else:
        need.status = NeedStatus.NEW
    need.version += 1
    need.save(update_fields=["approved_support", "status", "version", "updated_at"])
    after = {"status": need.status, "approved_support": str(approved)}
    if old != after:
        audit(need, actor, "تحديث حالة الدعم", old, after)


@transaction.atomic
def add_candidates(pk, version, ids, filters, actor):
    need = lock_need(pk, version)
    if not need.is_active or need.status == NeedStatus.COMPLETE:
        raise Conflict("لا يمكن إضافة رعاة لبطاقة غير نشطة أو مكتملة الدعم.")
    if not ids or len(ids) > 100 or len(set(ids)) != len(ids):
        raise Conflict("اختر جهة واحدة على الأقل، دون تكرار، وبحد أقصى 100 جهة.")
    # Lock organizations before rechecking selected development states and shared program data.
    list(Partnership.objects.select_for_update().filter(pk__in=ids).order_by("pk"))
    from training_programs.models import TrainingProgram
    list(TrainingProgram.objects.select_for_update().filter(pk=need.program_id))
    eligible = set(candidates(need, filters).filter(pk__in=ids).values_list("pk", flat=True))
    if eligible != set(ids):
        raise Conflict("تغيّرت أهلية بعض الجهات أو أُضيفت مسبقًا. حدّث نتائج المطابقة قبل التأكيد.")
    for organization_id in sorted(ids):
        record = Sponsorship.objects.create(need=need, partnership_id=organization_id, updated_by=actor)
        audit(need, actor, "إضافة جهة مرشحة", after={**sponsor_data(record), "program": need.program_name, "matching_basis": "بيانات البرنامج: القطاع والتخصص وشكل الرعاية", "state": record.partnership.development_state_id}, sponsorship=record)
    recompute(need, actor)
    return need


def followup(pk, version, sponsorship_id, record_version, operation, data, files, actor):
    saved_paths = []
    try:
        with transaction.atomic():
            need = lock_need(pk, version)
            record = Sponsorship.objects.select_for_update().filter(pk=sponsorship_id, need=need).first()
            if not record or record.version != record_version:
                raise Conflict("تغيّر سجل الرعاية أو نُفذ الطلب مسبقًا. أعد فتحه.")
            if record.status == SponsorshipStatus.REJECTED or (operation not in {"notes", "allocate"} and record.status != SponsorshipStatus.NEW):
                raise Conflict("القرار نهائي لهذا السجل؛ لا يمكن تكرار الاعتماد أو التراجع عن الرفض.")
            if operation not in {"notes", "approve", "reject", "allocate"}:
                raise Conflict("عملية غير متاحة.")
            if operation == "allocate" and (record.status != SponsorshipStatus.APPROVED or record.allocations.exists()):
                raise Conflict("التوزيع الاستكمالي متاح للمساهمات المعتمدة القديمة غير الموزّعة فقط.")
            if not need.is_active:
                raise Conflict("فعّل البطاقة قبل متابعة الرعاية.")
            form = FollowupForm(data, files, operation=operation, need=need, record=record)
            valid = form.is_valid()
            if operation == "approve" and form.cleaned_data.get("amount") is not None and form.cleaned_data["amount"] > need.remaining:
                raise Conflict("المساهمة تتجاوز المبلغ المتبقي. حدّث الصفحة وراجع إجمالي الدعم.")
            if not valid:
                raise InvalidForm(form)
            clean, before = form.cleaned_data, sponsor_data(record)
            if operation != "allocate":
                record.notes = clean["notes"]
            organization = Partnership.objects.select_for_update().get(pk=record.partnership_id)
            if operation == "approve":
                from training_programs.models import TrainingProgram
                list(TrainingProgram.objects.select_for_update().filter(pk=need.program_id))
                if not eligible_for_approval(need, organization.pk):
                    raise Conflict("لم تعد الجهة متوافقة مع بيانات برنامج الحاجة، أو أصبحت غير نشطة، أو حالة تطورها غير معرّفة. راجع بياناتها قبل الاعتماد.")
                if clean["amount"] > need.remaining:
                    raise Conflict("المساهمة تتجاوز المبلغ المتبقي. حدّث الصفحة وراجع إجمالي الدعم.")
                record.amount = clean["amount"]
                from levels.models import Level
                from .funding import level_key
                level = Level.objects.select_for_update().filter(funding_key=level_key(record.amount, need.total_cost)).first()
                if level is None:
                    raise Conflict("مستوى الرعاية التلقائي غير معرّف. طبّق ترحيلات المستويات أولًا.")
                record.level = level
                record.level_name = level.name
                record.status = SponsorshipStatus.APPROVED
                record.decided_at = timezone.now()
                if organization.development_state_id != DevelopmentState.CARE:
                    if not StateColor.objects.filter(pk=DevelopmentState.CARE).exists():
                        raise Conflict("حالة رعاية غير معرفة. طبّق ترحيلات حالات التطور أولًا.")
                    previous = organization.development_state_id
                    if not organization.development_history.filter(state_id=previous).exists():
                        DevelopmentHistory.objects.create(partnership=organization, state_id=previous, entered_at=organization.development_state_at)
                    entered = timezone.now()
                    DevelopmentHistory.objects.create(partnership=organization, state_id=DevelopmentState.CARE, entered_at=entered)
                    organization.development_state_id = DevelopmentState.CARE
                    organization.development_state_at = entered
                    organization.version += 1
                    organization.save(update_fields=["development_state", "development_state_at", "version", "updated_at"])
                    audit(need, actor, "انتقال الجهة إلى رعاية", {"organization": organization.name, "state": previous}, {"organization": organization.name, "state": DevelopmentState.CARE, "entered_at": entered.isoformat()}, record)
            elif operation == "reject":
                record.status = SponsorshipStatus.REJECTED
                record.rejection_reason = clean["rejection_reason"].strip()
                record.decided_at = timezone.now()
            record.version += 1
            record.updated_by = actor
            record.updated_at = timezone.now()
            record.save()
            if operation in {"approve", "allocate"}:
                SponsorshipAllocation.objects.bulk_create([
                    SponsorshipAllocation(sponsorship=record, expense_line=line, amount=value)
                    for line, value in clean["allocations"]
                ])
            if operation == "approve":
                storage = willingness_storage()
                for upload in clean["attachments"]:
                    name = "market-support/" + uuid.uuid4().hex + Path(upload.name).suffix.lower()
                    saved_paths.append(name)
                    actual = storage.save(name, upload)
                    if actual != name:
                        saved_paths.append(actual)
                    SupportAttachment.objects.create(sponsorship=record, file=actual, original_name=safe_filename(upload.name), size=upload.size, content_type=upload.verified_content_type, uploaded_by=actor)
            audit(need, actor, {"notes": "تسجيل نتيجة التواصل", "approve": "اعتماد مساهمة", "reject": "رفض جهة مرشحة", "allocate": "توزيع مساهمة سابقة على بنود الصرف"}[operation], before, {**sponsor_data(record), "attachments": [safe_filename(u.name) for u in clean["attachments"]]}, record)
            recompute(need, actor)
            return need
    except Exception:
        delete_private_files(saved_paths)
        raise


@transaction.atomic
def card_action(pk, version, operation, actor):
    need = lock_need(pk, version)
    ensure_allowed(need, operation, not need.is_active if operation == "toggle" else None)
    before = card_data(need)
    if operation == "delete":
        if need.sponsorships.filter(status=SponsorshipStatus.APPROVED).exists():
            raise Conflict("لا يمكن حذف بطاقة مرتبطة بمتابعة الرعاية أو إيقافها. تبقى بيانات المتابعة والدعم محفوظة.")
        audit(need, actor, "حذف البطاقة", before)
        need.delete()
    elif operation == "toggle":
        need.is_active = not need.is_active
        need.version += 1
        need.save(update_fields=["is_active", "version", "updated_at"])
        audit(need, actor, "تغيير حالة تفعيل البطاقة", before, card_data(need))
    else:
        raise Conflict("عملية غير متاحة.")
