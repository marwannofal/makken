
from core.dependencies import DependencyBlocked, ensure_allowed, blocked_context
# MAKKEN LINKED RECORD PROTECTION v1
import hashlib

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.db.models.deletion import ProtectedError, RestrictedError
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from accounts.security import add_login_headers
from specializations.models import Specialization
from .forms import SectorForm
from .models import Sector

from core.settings_filters import apply as _makken_settings_apply, context as _makken_settings_context, redirect as _makken_settings_redirect

SNAPSHOT_SALT = "makken.sectors.snapshot.v1"
CONFIRM_SALT = "makken.sectors.confirm.v1"
TOKEN_AGE = 20 * 60
OPERATIONS = {"add", "edit", "delete", "toggle"}


def _sign(payload, user, salt=SNAPSHOT_SALT):
    return signing.dumps({**payload, "user": str(user.pk)}, salt=salt, compress=True)


def _load(token, user, salt=SNAPSHOT_SALT):
    if not isinstance(token, str) or len(token) > 262144:
        raise signing.BadSignature("Invalid token")
    payload = signing.loads(token, salt=salt, max_age=TOKEN_AGE)
    if not isinstance(payload, dict) or payload.get("user") != str(user.pk) or payload.get("operation") not in OPERATIONS:
        raise signing.BadSignature("Invalid token")
    return payload


def _fingerprint(items):
    value = ";".join(f"{item.pk}:{item.version}" for item in sorted(items, key=lambda item: item.pk))
    return hashlib.sha256(value.encode()).hexdigest()


def _snapshot(item, operation, user):
    return _sign({"operation": operation, "id": item.pk, "version": item.version,
                  "assignments": _fingerprint(item.specializations.all())}, user)


def _unchanged(item, payload, owned=None):
    return (item is not None and item.version == payload.get("version")
            and _fingerprint(item.specializations.all() if owned is None else owned) == payload.get("assignments"))


def _pending(operation, item, name, active, selected, user):
    ensure_allowed(item, operation, active)
    owned = list(item.specializations.all()) if item else []
    payload = {"operation": operation, "id": item.pk if item else None, "version": item.version if item else None,
               "assignments": _fingerprint(owned), "name": name, "is_active": active,
               "selected": sorted(s.pk for s in selected), "selected_state": _fingerprint(selected)}
    titles = {"add": "تأكيد إضافة القطاع", "edit": "تأكيد تعديل القطاع", "delete": "تأكيد حذف القطاع", "toggle": "تأكيد تغيير حالة القطاع"}
    buttons = {"add": "تأكيد الإضافة", "edit": "تأكيد التعديل", "delete": "نعم، حذف القطاع", "toggle": "تأكيد التغيير"}
    return {**payload, "old_name": item.name if item else None, "old_active": item.is_active if item else None,
            "specializations": selected, "old_specializations": owned, "title": titles[operation],
            "button": buttons[operation], "token": _sign(payload, user, CONFIRM_SALT)}


def _stale():
    return "تغيّر القطاع أو أحد تخصصاته، أو تم تنفيذ الطلب مسبقًا. أعد فتح النموذج وراجع البيانات."


class AssignmentConflict(Exception):
    pass


def _apply(payload, user):
    """Lock sector then specialization rows in PK order; availability must hold at commit."""
    operation = payload["operation"]
    selected_ids = payload.get("selected")
    if (not isinstance(payload.get("name"), str) or type(payload.get("is_active")) is not bool
            or not isinstance(selected_ids, list)
            or any(type(pk) is not int or pk < 1 for pk in selected_ids) or len(set(selected_ids)) != len(selected_ids)):
        raise signing.BadSignature("Invalid confirmation")
    with transaction.atomic():
        item = None
        if operation != "add":
            item = Sector.objects.select_for_update().filter(pk=payload.get("id")).first()
            if item is None:
                raise AssignmentConflict(_stale())
        query = Q(pk__in=selected_ids)
        if item:
            query |= Q(sector_id=item.pk)
        locked = list(Specialization.objects.select_for_update().filter(query).order_by("pk"))
        owned = [s for s in locked if item and s.sector_id == item.pk]
        if item and not _unchanged(item, payload, owned):
            raise AssignmentConflict(_stale())
        ensure_allowed(item, operation, payload["is_active"])
        if operation in {"add", "edit"}:
            selected_set = set(selected_ids)
            selected = [s for s in locked if s.pk in selected_set]
            if _fingerprint(selected) != payload.get("selected_state"):
                raise AssignmentConflict("تغيّرت بيانات أحد التخصصات منذ المراجعة. أعد فتح النموذج وراجع البيانات.")
            if len(selected) != len(selected_ids) or any(s.sector_id is not None and (item is None or s.sector_id != item.pk) for s in selected):
                raise AssignmentConflict("تم ربط أحد التخصصات بقطاع آخر أو حُذف. لم يُحفظ أي تغيير. أعد فتح النموذج.")
            form = SectorForm({"operation": operation, "name": payload["name"], "is_active": "1" if payload["is_active"] else "0",
                               "snapshot": "validated", "specializations": selected_ids}, instance_id=item.pk if item else None)
            if not form.is_valid():
                raise AssignmentConflict("تعذّر الحفظ. راجع الاسم والتخصصات المتاحة ثم حاول مجددًا.")
            if item is None:
                item = Sector.objects.create(name=form.cleaned_data["name"], is_active=payload["is_active"])
            else:
                item.name, item.is_active = form.cleaned_data["name"], payload["is_active"]
                item.version += 1
                item.save()
            released = [s.pk for s in owned if s.pk not in selected_ids]
            # MAKKEN PARTNERSHIP SPECIALIZATION GUARD
            from partnerships.models import OfferingSpecialization
            if OfferingSpecialization.objects.filter(specialization_id__in=released).exists():
                raise AssignmentConflict("لا يمكن إلغاء ربط تخصص مستخدم في سجل شراكة. عدّل بند الشراكة أولًا.")
            acquired = [s.pk for s in selected if s.sector_id != item.pk]
            now = timezone.now()
            if released:
                Specialization.objects.filter(pk__in=released).update(sector=None, version=F("version") + 1, updated_at=now)
            if acquired:
                Specialization.objects.filter(pk__in=acquired).update(sector=item, version=F("version") + 1, updated_at=now)
        elif operation == "toggle":
            item.is_active = payload["is_active"]
            item.version += 1
            item.save(update_fields=["is_active", "version", "updated_at"])
        else:
            # Release children without deleting specializations; invalidate their stale confirmation tokens.
            Specialization.objects.filter(sector=item).update(sector=None, version=F("version") + 1, updated_at=timezone.now())
            item.delete()


@login_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def index(request):
    name = request.user.get_short_name() or request.user.get_username()
    add_snapshot = _sign({"operation": "add"}, request.user)
    context = {"page_heading": "إدارة القطاعات", "active_page": "sectors", "display_name": name,
               "avatar_initial": name[:1], "add_snapshot": add_snapshot,
               "editor_form": SectorForm(initial={"operation": "add", "snapshot": add_snapshot, "is_active": "1"})}
    status = 200
    try:
        if request.method == "POST":
            action = request.POST.get("action")
            if action == "preview":
                snapshot = _load(request.POST.get("snapshot"), request.user)
                operation = snapshot["operation"]
                item = None
                if operation != "add":
                    item = Sector.objects.prefetch_related("specializations").filter(pk=snapshot.get("id")).first()
                    if not _unchanged(item, snapshot):
                        raise AssignmentConflict(_stale())
                if operation in {"add", "edit"}:
                    if request.POST.get("operation") != operation:
                        raise signing.BadSignature("Operation changed")
                    form = SectorForm(request.POST, instance_id=item.pk if item else None)
                    if form.is_valid():
                        new_name, active = form.cleaned_data["name"], form.cleaned_data["is_active"] == "1"
                        selected = list(form.cleaned_data["specializations"])
                        if item and item.name == new_name and item.is_active == active and set(s.pk for s in selected) == set(s.pk for s in item.specializations.all()):
                            context["notice"] = "لم يتم إجراء أي تغييرات على القطاع."
                        else:
                            context["pending"] = _pending(operation, item, new_name, active, selected, request.user)
                    else:
                        context.update(editor_form=form, editing=True, editor_operation=operation)
                        status = 400
                else:
                    active = not item.is_active if operation == "toggle" else item.is_active
                    context["pending"] = _pending(operation, item, item.name, active, list(item.specializations.all()), request.user)
            elif action == "confirm":
                payload = _load(request.POST.get("token"), request.user, CONFIRM_SALT)
                _apply(payload, request.user)
                message = {"add": "تمت إضافة القطاع بنجاح.", "edit": "تم تعديل القطاع بنجاح.", "delete": "تم حذف القطاع غير المرتبط بنجاح.", "toggle": "تم تحديث حالة القطاع بنجاح."}[payload["operation"]]
                messages.success(request, message)
                return add_login_headers(_makken_settings_redirect(request, "sectors:index"))
            else:
                context["error"], status = "طلب غير صالح. لم يتم تغيير السجلات.", 400
        else:
            edit = request.GET.get("edit")
            if edit == "new":
                context.update(editing=True, editor_operation="add")
            elif edit:
                item = Sector.objects.prefetch_related("specializations").filter(pk=int(edit)).first() if edit.isascii() and edit.isdecimal() and len(edit) <= 18 else None
                if item:
                    context.update(editing=True, editor_operation="edit", editor_form=SectorForm(instance_id=item.pk, initial={
                        "operation": "edit", "snapshot": _snapshot(item, "edit", request.user), "name": item.name,
                        "is_active": "1" if item.is_active else "0", "specializations": [s.pk for s in item.specializations.all()]}))
                else:
                    context["error"], status = "القطاع المطلوب غير موجود.", 404
    except DependencyBlocked as exc:
        context.update(blocked_context(exc))
        status = 409
    except signing.BadSignature:
        context["error"], status = "انتهت صلاحية الطلب أو تغيّر محتواه. أعد فتح الصفحة وحاول مجددًا.", 400
    except AssignmentConflict as exc:
        context["error"], status = str(exc), 409
    except (IntegrityError, ProtectedError, RestrictedError):
        context["error"], status = "تعذّر تنفيذ الطلب. الاسم مستخدم بالفعل أو تغيّرت التخصصات. لم يُحفظ أي تغيير.", 409
    page = Paginator(_makken_settings_apply(request, Sector.objects.prefetch_related("specializations").all()), 10).get_page(request.GET.get("page"))
    rows = []
    for item in page:
        rows.append({"id": item.pk, "name": item.name, "is_active": item.is_active, "specializations": list(item.specializations.all()),
                     "edit_snapshot": _snapshot(item, "edit", request.user), "toggle_snapshot": _snapshot(item, "toggle", request.user),
                     "delete_snapshot": _snapshot(item, "delete", request.user)})
    context.update(rows=rows, page_obj=page)
    # MAKKEN SETTINGS FILTER CONTEXT
    context.update(_makken_settings_context(request))
    return add_login_headers(render(request, "sectors/index.html", context, status=status))
