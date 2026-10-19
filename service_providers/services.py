"""Transactional writes, reference validation, idempotency and immutable audit entries."""
import json
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from entities.models import Entity, normalize_name
from regions.models import Region
from sectors.models import Sector
from specializations.models import Specialization
from sponsorship_shapes.models import SponsorshipShape
from care_states.models import DevelopmentState, StateColor
from partnerships.models import Partnership, PartnershipOffering, DevelopmentHistory
from partnerships.attachment_storage import delete_private_files
from partnerships.willingness import save_supporting_files
from .forms import ProviderForm, ConversionForm, coverage_data
from .models import ServiceProvider, ProviderCoverage, ProviderAudit


class Conflict(Exception):
    pass


def snapshot(item):
    if not item:
        return {}
    return {"name": item.name, "representative": item.representative, "phone_country": item.phone_country, "phone": item.phone, "email": item.email, "provider_type": item.provider_type, "scope": item.scope, "is_active": item.is_active, "coverage": coverage_data(item), "partnership": item.converted_partnership_id, "converted_at": item.converted_at.isoformat() if item.converted_at else None, "version": item.version}


def audit(item, action, user, before):
    return ProviderAudit.objects.create(provider=item, provider_key=item.pk, provider_name=item.name, action=action, actor=user, actor_name=user.get_username(), before=before, after={} if action == "delete" else snapshot(item))


def lock_references(data):
    rows = json.loads(data["coverage"]) if isinstance(data["coverage"], str) else data["coverage"]
    regions = sorted({r["region"] for r in rows})
    specs = sorted({s for r in rows for s in r["specializations"]})
    list(Region.objects.select_for_update().filter(pk__in=regions).order_by("pk"))
    sector_ids = set(Specialization.objects.filter(pk__in=specs).exclude(sector_id=None).values_list("sector_id", flat=True))
    # Match the existing partnership writer's Sector -> Specialization order.
    list(Sector.objects.select_for_update().filter(pk__in=sector_ids).order_by("pk"))
    selected = list(Specialization.objects.select_for_update().filter(pk__in=specs).order_by("pk"))
    if any(spec.sector_id and spec.sector_id not in sector_ids for spec in selected):
        raise Conflict("تغيّر قطاع أحد التخصصات أثناء المراجعة. حدّث الاختيارات قبل المتابعة.")


def save_provider(payload, user):
    with transaction.atomic():
        item = ServiceProvider.objects.select_for_update().filter(pk=payload.get("id")).first() if payload.get("id") else None
        if payload.get("id") and (not item or item.version != payload["version"]):
            raise Conflict("تغيّر سجل المزود أو حُذف. أعد فتحه وراجع أحدث البيانات.")
        if not payload.get("id"):
            repeated = ServiceProvider.objects.filter(request_key=payload["nonce"]).first()
            if repeated:
                return repeated
        lock_references(payload["data"])
        form = ProviderForm(payload["data"], instance=item)
        if not form.is_valid():
            raise Conflict("تغيّرت بعض الاختيارات أو تكرر الاسم منذ المراجعة. أعد فتح النموذج وتحقق من البيانات.")
        data, before = form.cleaned_data, snapshot(item)
        action = "edit" if item else "create"
        if not item:
            item = ServiceProvider(created_by=user, request_key=payload["nonce"])
        else:
            item.version += 1
        for key in ["name", "representative", "phone_country", "phone", "email", "provider_type", "scope"]:
            setattr(item, key, data[key])
        item.is_active = data["is_active"] == "1"
        item.updated_by = user
        item.save()
        keep = []
        for position, row in enumerate(data["coverage"]):
            coverage, _ = ProviderCoverage.objects.update_or_create(provider=item, region_id=row["region"], defaults={"is_active": row["is_active"], "position": position})
            coverage.specializations.set(row["specializations"])
            keep.append(coverage.pk)
        item.coverage.exclude(pk__in=keep).delete()
        audit(item, action, user, before)
        return item


def row_action(payload, user):
    with transaction.atomic():
        item = ServiceProvider.objects.select_for_update().filter(pk=payload["id"]).first()
        if not item or item.version != payload["version"]:
            raise Conflict("تغيّر السجل أو نُفّذ الطلب مسبقًا. حدّث القائمة وحاول مجددًا.")
        before = snapshot(item)
        if payload["operation"] == "delete":
            if item.converted_partnership_id:
                raise Conflict("لا يمكن حذف مزود حُوّل إلى جهة في سجل الشراكات. يمكنك إيقاف سجل المزود مع الحفاظ على العلاقة والتاريخ.")
            audit(item, "delete", user, before)
            item.delete()
        elif payload["operation"] == "toggle":
            item.is_active = not item.is_active
            item.version += 1
            item.updated_by = user
            item.save()
            audit(item, "toggle", user, before)
        else:
            raise Conflict("العملية غير متاحة.")


def convert_provider(payload, posted, files, user):
    saved_paths = []
    try:
        with transaction.atomic():
            item = ServiceProvider.objects.select_for_update().filter(pk=payload["id"]).first()
            if not item:
                raise Conflict("لم يعد سجل المزود متاحًا.")
            if item.converted_partnership_id:
                return item.converted_partnership
            if item.version != payload["version"]:
                raise Conflict("تغيّر سجل المزود. أعد فتح نافذة التحويل وراجع بياناته.")
            if not item.is_active:
                raise Conflict("فعّل سجل المزود قبل تحويله إلى رغبة.")
            # Follow Entity -> Sector -> Specialization -> Shape, as in partnerships.
            list(Entity.objects.select_for_update().filter(pk=posted.get("entity") or None).order_by("pk"))
            if item.provider_type == "government" and not posted.get("entity"):
                list(Entity.objects.select_for_update().filter(entity_type="government", is_active=True).order_by("pk"))
            rows = list(item.coverage.filter(is_active=True).prefetch_related("specializations"))
            reference_data = {"coverage": [{"region": r.region_id, "specializations": [s.pk for s in r.specializations.all()], "is_active": True} for r in rows]}
            lock_references(reference_data)
            active_region_ids = set(Region.objects.filter(pk__in=[r.region_id for r in rows], is_active=True).values_list("pk", flat=True))
            selected_ids = {s.pk for r in rows if r.region_id in active_region_ids for s in r.specializations.all()}
            specs = list(Specialization.objects.filter(pk__in=selected_ids, is_active=True, sector__is_active=True).select_related("sector").order_by("pk"))
            if not specs:
                raise Conflict("يلزم وجود منطقة نشطة وبند نشط وتخصص نشط مرتبط بقطاع نشط قبل التحويل.")
            list(SponsorshipShape.objects.select_for_update().filter(pk=posted.get("sponsorship_shape") or None).order_by("pk"))
            form = ConversionForm(posted, files, provider=item)
            if not form.is_valid():
                raise ValidationError(form.errors)
            if Partnership.objects.filter(name_key=normalize_name(item.name).casefold()).exists():
                raise Conflict("توجد جهة بهذا الاسم في سجل الشراكات بالفعل. راجع سجل الشراكات؛ لن تُنشأ جهة مكررة.")
            if not StateColor.objects.filter(pk=DevelopmentState.WILLINGNESS).exists():
                raise Conflict("حالة رغبة غير موجودة. راجع ترحيلات حالات التطور.")
            clean, before, now = form.cleaned_data, snapshot(item), timezone.now()
            partner = Partnership.objects.create(name=item.name, representative=normalize_name(clean["representative"]), phone_country=clean["phone_country"], phone=clean["phone"], email=clean["email"].casefold(), financial_capacity=clean["financial_capacity"], entity=clean["entity"], scope=item.scope, is_active=True, development_state_id=DevelopmentState.WILLINGNESS, development_state_at=now, preliminary_agreement_type=clean["agreement_type"], request_key=payload["nonce"], created_by=user)
            # No invented capability transition: this is a new willing entity.
            DevelopmentHistory.objects.create(partnership=partner, state_id=DevelopmentState.WILLINGNESS, entered_at=now)
            for position, spec in enumerate(specs):
                offering = PartnershipOffering.objects.create(partnership=partner, sector_id=spec.sector_id, sponsorship_shape=clean["sponsorship_shape"], is_active=True, position=position)
                offering.specializations.set([spec])
            save_supporting_files(partner, clean, user, saved_paths)
            partner.save(update_fields=["preliminary_agreement_type"])
            item.converted_partnership = partner
            item.converted_at = now
            item.version += 1
            item.updated_by = user
            item.save()
            audit(item, "convert", user, before)
            return partner
    except Exception:
        delete_private_files(saved_paths)
        raise
