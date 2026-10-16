import hashlib
import json
import uuid

import phonenumbers
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q, Prefetch
from django.db.models.deletion import ProtectedError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from urllib.parse import urlencode

from accounts.security import add_login_headers
from care_states.models import DevelopmentState, StateColor
from entities.models import Entity, EntityType, EntityBranch
from sectors.models import Sector
from specializations.models import Specialization
from sponsorship_shapes.models import SponsorshipShape
from .forms import PartnershipForm, offering_data
from .models import Partnership, PartnershipOffering, DevelopmentHistory, Scope

SALT = "makken.partnerships.v1"
AGE = 20 * 60


class Conflict(Exception):
    pass


def _sign(data, user):
    return signing.dumps({**data, "user": str(user.pk)}, salt=SALT, compress=True)


def _load(token, user, kind):
    if not isinstance(token, str) or len(token) > 120000:
        raise signing.BadSignature
    data = signing.loads(token, salt=SALT, max_age=AGE)
    if not isinstance(data, dict) or data.get("user") != str(user.pk) or data.get("kind") != kind:
        raise signing.BadSignature
    return data


def _base(request, title, active):
    name = request.user.get_short_name() or request.user.get_username()
    return {"page_heading": title, "active_page": active, "display_name": name, "avatar_initial": name[:1]}


def _query():
    return Partnership.objects.select_related("entity", "development_state").prefetch_related(
        Prefetch("offerings", queryset=PartnershipOffering.objects.select_related("sector", "sponsorship_shape").prefetch_related("specializations")),
        "development_history__state")


def _history(item):
    if not item:
        return []
    entered = {entry.state_id: entry.entered_at for entry in item.development_history.all()}
    return [{"label": label, "color": color.color if (color := StateColor.objects.filter(pk=value).first()) else "#74888b", "date": entered.get(value), "current": item.development_state_id == value} for value, label in DevelopmentState.choices]


def _fingerprint(data, lock=False):
    rows = json.loads(data["offerings"])
    selections = [(Entity, [int(data["entity"])]), (Sector, sorted({r["sector"] for r in rows})), (Specialization, sorted({s for r in rows for s in r["specializations"]})), (SponsorshipShape, sorted({r["shape"] for r in rows}))]
    values = []
    for model, ids in selections:
        query = model.objects.filter(pk__in=ids).order_by("pk")
        if lock:
            query = query.select_for_update()
        fields = ["pk", "version", "is_active"]
        if model is Specialization:
            fields.append("sector_id")
        values.append([model.__name__, list(query.values_list(*fields))])
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def _serialized(cleaned):
    return {"name": cleaned["name"], "representative": cleaned["representative"], "phone_country": cleaned["phone_country"], "phone": cleaned["phone"], "email": cleaned["email"], "entity_type": cleaned["entity_type"], "entity": str(cleaned["entity"].pk), "scope": cleaned["scope"], "is_active": cleaned["is_active"], "offerings": json.dumps(cleaned["offerings"])}


def _initial(item):
    if not item:
        return {"phone_country": "SA", "is_active": "1", "offerings": "[]"}
    return {"name": item.name, "representative": item.representative, "phone_country": item.phone_country, "phone": item.phone, "email": item.email, "entity_type": item.entity.entity_type, "entity": item.entity_id, "scope": item.scope, "is_active": "1" if item.is_active else "0", "offerings": json.dumps(offering_data(item))}


def _catalog(item):
    old = offering_data(item)
    sector_ids, shape_ids = {r["sector"] for r in old}, {r["shape"] for r in old}
    spec_ids = {s for r in old for s in r["specializations"]}
    return {
        "sectors": list(Sector.objects.filter(Q(is_active=True) | Q(pk__in=sector_ids)).values("id", "name", "is_active")),
        "specializations": list(Specialization.objects.filter(Q(is_active=True) | Q(pk__in=spec_ids)).values("id", "name", "sector_id", "is_active")),
        "shapes": list(SponsorshipShape.objects.filter(Q(is_active=True) | Q(pk__in=shape_ids)).values("id", "name", "description", "is_active")),
        "entities": list(Entity.objects.filter(Q(is_active=True) | Q(pk=item.entity_id if item else None)).values("id", "name", "entity_type", "is_active")),
        "countries": [{"id": code, "dial": "+" + str(phonenumbers.country_code_for_region(code))} for code in sorted(phonenumbers.SUPPORTED_REGIONS - {"IL"})],
    }


def _save(payload, user):
    with transaction.atomic():
        pk = payload.get("id")
        item = Partnership.objects.select_for_update().filter(pk=pk).first() if pk else None
        if pk and (not item or item.version != payload.get("version")):
            raise Conflict("تغيّر السجل أو حُذف منذ فتحه. أعد فتح الصفحة وراجع أحدث البيانات.")
        if not pk:
            repeated = Partnership.objects.filter(request_key=payload["nonce"]).first()
            if repeated:
                return repeated
        data = payload["data"]
        if _fingerprint(data, lock=True) != payload.get("catalog"):
            raise Conflict("تغيّرت بيانات أحد الكيانات أو القطاعات أو التخصصات أو أشكال الرعاية. راجع الاختيارات مجددًا.")
        form = PartnershipForm(data, instance=item)
        if not form.is_valid():
            raise Conflict("تعذّر الحفظ. راجع الاسم والبيانات المرتبطة؛ قد تكون تغيّرت منذ المراجعة.")
        clean = form.cleaned_data
        new = item is None
        if new:
            if not StateColor.objects.filter(pk=DevelopmentState.CAPABILITY).exists():
                raise Conflict("حالة قدرة غير موجودة. تأكد من تطبيق ترحيلات حالات تطور المنظمات للرعاية.")
            item = Partnership(request_key=payload["nonce"], created_by=user)
        for field in ["name", "representative", "phone_country", "phone", "email", "entity", "scope"]:
            setattr(item, field, clean[field])
        item.is_active = clean["is_active"] == "1"
        if not new:
            item.version += 1
        item.save()
        if new:
            DevelopmentHistory.objects.create(partnership=item, state_id=DevelopmentState.CAPABILITY, entered_at=item.development_state_at)
        item.offerings.all().delete()
        for position, row in enumerate(clean["offerings"]):
            offering = PartnershipOffering.objects.create(partnership=item, sector_id=row["sector"], sponsorship_shape_id=row["shape"], is_active=row["is_active"], position=position)
            offering.specializations.set(row["specializations"])
        return item


@login_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def editor(request, pk=None):
    item = get_object_or_404(_query(), pk=pk) if pk else None
    context = _base(request, "تعديل جهة لسجل الشراكات المحتملة التي لها القدرة" if item else "إضافة جهة لسجل الشراكات المحتملة التي لها القدرة", "partnership_editor")
    status, pending = 200, None
    snapshot = _sign({"kind": "editor", "id": pk, "version": item.version if item else None, "nonce": str(uuid.uuid4())}, request.user)
    form = PartnershipForm(initial=_initial(item), instance=item)
    try:
        if request.method == "POST":
            if len(request.body) > 150000:
                raise signing.BadSignature
            action = request.POST.get("action")
            if action == "preview":
                original = _load(request.POST.get("snapshot"), request.user, "editor")
                if original.get("id") != pk or (item and original.get("version") != item.version):
                    raise Conflict("تغيّر السجل منذ فتح النموذج. أعد فتح الصفحة قبل التعديل.")
                snapshot = request.POST["snapshot"]
                form = PartnershipForm(request.POST, instance=item)
                if form.is_valid():
                    data = _serialized(form.cleaned_data)
                    token = _sign({**original, "kind": "save", "data": data, "catalog": _fingerprint(data)}, request.user)
                    pending = {"title": "تأكيد تعديل الجهة" if item else "تأكيد إضافة الجهة", "name": data["name"], "token": token, "action": "save", "button": "تأكيد الحفظ"}
                else:
                    status = 400
            elif action == "confirm":
                payload = _load(request.POST.get("token"), request.user, "save")
                if payload.get("id") != pk:
                    raise signing.BadSignature
                form = PartnershipForm(payload["data"], instance=item)
                saved = _save(payload, request.user)
                messages.success(request, "تم حفظ بيانات الجهة بنجاح.")
                return add_login_headers(redirect("partnerships:edit", pk=saved.pk))
            else:
                raise signing.BadSignature
    except signing.BadSignature:
        context["error"], status = "انتهت صلاحية الطلب أو تغيّر محتواه. أعد فتح الصفحة وحاول مجددًا.", 400
    except (Conflict, IntegrityError, ProtectedError) as exc:
        context["error"], status = str(exc) if isinstance(exc, Conflict) else "تعذّر الحفظ؛ اسم الجهة مستخدم أو تغيّرت البيانات المرتبطة. لم يُحفظ أي تغيير.", 409
    raw_rows = form["offerings"].value() or "[]"
    try:
        drafts = json.loads(raw_rows)
        if not isinstance(drafts, list):
            drafts = []
    except (ValueError, TypeError):
        drafts = []
    context.update(item=item, form=form, snapshot=snapshot, pending=pending, catalog=_catalog(item), drafts=drafts, history=_history(item))
    return add_login_headers(render(request, "partnerships/editor.html", context, status=status))


def _search(query, term):
    if term in {"غير نشط", "غير فعال", "inactive"}:
        return query.filter(is_active=False)
    if term in {"نشط", "فعال", "active"}:
        return query.filter(is_active=True)
    for field, choices in [("entity__entity_type", EntityType.choices), ("entity__branch", EntityBranch.choices), ("scope", Scope.choices), ("development_state_id", DevelopmentState.choices)]:
        for value, label in choices:
            if term == label:
                return query.filter(**{field: value})
    for word in term.split()[:12]:
        condition = Q(name__icontains=word) | Q(representative__icontains=word) | Q(phone__icontains=word) | Q(email__icontains=word) | Q(entity__name__icontains=word) | Q(offerings__sector__name__icontains=word) | Q(offerings__specializations__name__icontains=word) | Q(offerings__sponsorship_shape__name__icontains=word)
        for field, choices in [("entity__entity_type", EntityType.choices), ("entity__branch", EntityBranch.choices), ("scope", Scope.choices), ("development_state_id", DevelopmentState.choices)]:
            found = [value for value, label in choices if word in label]
            if found:
                condition |= Q(**{field + "__in": found})
        if word in {"نشط", "فعال", "active"}:
            condition |= Q(is_active=True)
        if word in {"غير", "موقوف", "inactive"}:
            condition |= Q(is_active=False)
        query = query.filter(condition)
    return query.distinct()


@login_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def index(request):
    context = _base(request, "إدارة سجل الشراكات التي لها القدرة", "partnerships")
    status, pending = 200, None
    try:
        if request.method == "POST":
            action = request.POST.get("action")
            if action not in {"preview", "confirm"}:
                raise signing.BadSignature
            data = _load(request.POST.get("token"), request.user, "row" if action == "preview" else "row-confirm")
            if data.get("operation") not in {"delete", "toggle"}:
                raise signing.BadSignature
            with transaction.atomic():
                item = Partnership.objects.select_for_update().filter(pk=data.get("id")).first()
                if not item or item.version != data.get("version"):
                    raise Conflict("تغيّر هذا السجل أو حُذف، أو تم تنفيذ الطلب مسبقًا. حدّث القائمة وحاول مجددًا.")
                if action == "preview":
                    operation = data["operation"]
                    pending = {"title": "تأكيد حذف الجهة" if operation == "delete" else "تأكيد تغيير حالة السجل", "name": item.name, "action": operation, "button": "نعم، حذف الجهة" if operation == "delete" else "تأكيد التغيير", "token": _sign({**data, "kind": "row-confirm"}, request.user)}
                else:
                    if data["operation"] == "delete":
                        item.delete()
                        message = "تم حذف الجهة وبيانات شراكتها بنجاح."
                    else:
                        item.is_active = not item.is_active
                        item.version += 1
                        item.save(update_fields=["is_active", "version", "updated_at"])
                        message = "تم تحديث حالة السجل بنجاح."
                    messages.success(request, message)
                    return add_login_headers(redirect("partnerships:index"))
    except signing.BadSignature:
        context["error"], status = "انتهت صلاحية الطلب أو تغيّر محتواه. أعد فتح الصفحة وحاول مجددًا.", 400
    except (Conflict, IntegrityError, ProtectedError) as exc:
        context["error"], status = str(exc) if isinstance(exc, Conflict) else "تعذّر تنفيذ الطلب لوجود بيانات مرتبطة.", 409
    q = request.GET.get("q", "").strip()[:200]
    active = request.GET.get("status", "")
    query = _search(_query(), q)
    if active in {"1", "0"}:
        query = query.filter(is_active=active == "1")
    page = Paginator(query, 15).get_page(request.GET.get("page"))
    rows = []
    for item in page:
        token = {"kind": "row", "id": item.pk, "version": item.version}
        rows.append({"item": item, "toggle": _sign({**token, "operation": "toggle"}, request.user), "delete": _sign({**token, "operation": "delete"}, request.user)})
    detail = None
    if request.GET.get("detail"):
        value = request.GET["detail"]
        if not value.isascii() or not value.isdecimal() or len(value) > 18:
            raise Http404
        detail = get_object_or_404(_query(), pk=int(value))
    params = {"q": q, "status": active, "page": page.number}
    result_query = urlencode(params)
    context.update(rows=rows, page_obj=page, q=q, selected_status=active, pending=pending, detail=detail, history=_history(detail), result_query=result_query, list_url=reverse("partnerships:index") + "?" + result_query)
    return add_login_headers(render(request, "partnerships/index.html", context, status=status))
