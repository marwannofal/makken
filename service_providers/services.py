"""Transactional writes, reference validation, idempotency and immutable audit entries."""
from access_control.enforcement import service_operation
# MAKKEN RBAC INTEGRATION v1

from core.dependencies import DependencyBlocked, ensure_allowed, blocked_context
# MAKKEN LINKED RECORD PROTECTION v1
import json
from django.db import transaction
from regions.models import Region
from sectors.models import Sector
from specializations.models import Specialization
from training_programs.models import TrainingProgram
from .forms import ProviderForm, coverage_data
from .models import ServiceProvider, ProviderCoverage, ProviderAudit


class Conflict(Exception):
    pass


def snapshot(item):
    if not item:
        return {}
    return {"program": item.program_id, "name": item.name, "representative": item.representative, "phone_country": item.phone_country, "phone": item.phone, "email": item.email, "provider_type": item.provider_type, "scope": item.scope, "is_active": item.is_active, "coverage": coverage_data(item), "partnership": item.converted_partnership_id, "converted_at": item.converted_at.isoformat() if item.converted_at else None, "version": item.version}


def audit(item, action, user, before):
    return ProviderAudit.objects.create(provider=item, provider_key=item.pk, provider_name=item.name, action=action, actor=user, actor_name=user.get_username(), before=before, after={} if action == "delete" else snapshot(item))


def lock_references(data):
    if data.get("program"):
        list(TrainingProgram.objects.select_for_update().filter(pk=data["program"]))
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


@service_operation('service_providers', 'save_provider')
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
        ensure_allowed(item, "edit", form.cleaned_data["is_active"] == "1")
        data, before = form.cleaned_data, snapshot(item)
        action = "edit" if item else "create"
        if not item:
            item = ServiceProvider(created_by=user, request_key=payload["nonce"])
        else:
            item.version += 1
        for key in ["name", "representative", "phone_country", "phone", "email", "provider_type", "scope"]:
            setattr(item, key, data[key])
        item.is_active = data["is_active"] == "1"
        item.program_id = data.get("program")
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


@service_operation('service_providers', 'row_action')
def row_action(payload, user):
    with transaction.atomic():
        item = ServiceProvider.objects.select_for_update().filter(pk=payload["id"]).first()
        if not item or item.version != payload["version"]:
            raise Conflict("تغيّر السجل أو نُفّذ الطلب مسبقًا. حدّث القائمة وحاول مجددًا.")
        ensure_allowed(item, payload["operation"], not item.is_active if payload["operation"] == "toggle" else None)
        before = snapshot(item)
        if payload["operation"] == "delete":
            if item.converted_partnership_id:
                raise Conflict("لا يمكن حذف مزود مرتبط بسجل الشراكات أو إيقافه قبل معالجة الارتباط.")
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


