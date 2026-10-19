
from core.dependencies import DependencyBlocked, ensure_allowed, blocked_context
# MAKKEN LINKED RECORD PROTECTION v1
import hashlib

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError, RestrictedError
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from accounts.security import add_login_headers
from expense_items.models import ExpenseItem
from .forms import TrainingProgramForm
from .models import TrainingProgram

from core.settings_filters import apply as _makken_settings_apply, context as _makken_settings_context, redirect as _makken_settings_redirect

SNAPSHOT_SALT = "makken.training_programs.snapshot.v2"
CONFIRM_SALT = "makken.training_programs.confirm.v2"
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


def _values(item):
    return {"name": item.name, "category": item.category, "training_types": item.training_types, "is_active": item.is_active}


def _snapshot(item, operation, user):
    return _sign({"operation": operation, "id": item.pk, "version": item.version,
                  "links": _fingerprint(item.expense_items.all())}, user)


def _unchanged(item, payload, linked=None):
    return (item is not None and item.version == payload.get("version")
            and _fingerprint(item.expense_items.all() if linked is None else linked) == payload.get("links"))


def _pending(operation, item, values, selected, user):
    ensure_allowed(item, operation, values["is_active"])
    linked = list(item.expense_items.all()) if item else []
    payload = {**values, "operation": operation, "id": item.pk if item else None, "version": item.version if item else None,
               "links": _fingerprint(linked), "selected": sorted(s.pk for s in selected), "selected_state": _fingerprint(selected)}
    titles = {"add": "تأكيد إضافة البرنامج", "edit": "تأكيد تعديل البرنامج", "delete": "تأكيد حذف البرنامج", "toggle": "تأكيد تغيير حالة البرنامج"}
    buttons = {"add": "تأكيد الإضافة", "edit": "تأكيد التعديل", "delete": "نعم، حذف البرنامج", "toggle": "تأكيد التغيير"}
    return {**payload, "old": {**_values(item), "category_label": item.get_category_display(), "type_labels": item.training_type_labels} if item else None,
            "category_label": TrainingProgram.Category(values["category"]).label,
            "type_labels": [TrainingProgram.TrainingType(value).label for value in values["training_types"]],
            "expense_items": selected, "old_expense_items": linked, "title": titles[operation], "button": buttons[operation],
            "token": _sign(payload, user, CONFIRM_SALT)}


def _stale():
    return "تغيّر البرنامج أو أحد بنود الصرف المرتبطة به، أو تم تنفيذ الطلب مسبقًا. أعد فتح النموذج وراجع البيانات."


class ProgramConflict(Exception):
    pass


def _apply(payload):
    operation = payload["operation"]
    selected_ids, types = payload.get("selected"), payload.get("training_types")
    if (not isinstance(payload.get("name"), str) or type(payload.get("is_active")) is not bool
            or payload.get("category") not in TrainingProgram.Category.values
            or not isinstance(types, list) or len(types) != 1 or any(type(value) is not str or value not in TrainingProgram.TrainingType.values for value in types)
            or len(set(types)) != len(types) or not isinstance(selected_ids, list)
            or any(type(pk) is not int or pk < 1 for pk in selected_ids) or len(set(selected_ids)) != len(selected_ids)):
        raise signing.BadSignature("Invalid confirmation")
    with transaction.atomic():
        item = None
        current_ids = set()
        if operation != "add":
            item = TrainingProgram.objects.select_for_update().filter(pk=payload.get("id")).first()
            if item is None:
                raise ProgramConflict(_stale())
            current_ids = set(item.expense_items.values_list("pk", flat=True))
        # Lock shared catalogue entries in a stable order; never reserve them for a program.
        locked = list(ExpenseItem.objects.select_for_update().filter(pk__in=current_ids | set(selected_ids)).order_by("pk"))
        linked = [expense for expense in locked if expense.pk in current_ids]
        if item and not _unchanged(item, payload, linked):
            raise ProgramConflict(_stale())
        ensure_allowed(item, operation, payload["is_active"])
        if operation in {"add", "edit"}:
            selected_set = set(selected_ids)
            selected = [expense for expense in locked if expense.pk in selected_set]
            if len(selected) != len(selected_ids) or _fingerprint(selected) != payload.get("selected_state"):
                raise ProgramConflict("تغيّرت بيانات أحد بنود الصرف أو حُذف منذ المراجعة. لم يُحفظ أي تغيير. أعد فتح النموذج.")
            form = TrainingProgramForm({"operation": operation, "snapshot": "validated", "name": payload["name"],
                                        "category": payload["category"], "training_types": types[0], "expense_items": selected_ids,
                                        "is_active": "1" if payload["is_active"] else "0"}, instance_id=item.pk if item else None)
            if not form.is_valid():
                raise ProgramConflict("تعذّر الحفظ. راجع اسم البرنامج والتصنيف وبنود الصرف وأنواع التدريب.")
            if item is None:
                item = TrainingProgram()
            else:
                item.version += 1
            item.name, item.category = form.cleaned_data["name"], form.cleaned_data["category"]
            item.is_training = TrainingProgram.TrainingType.TRAINING in form.cleaned_data["training_types"]
            item.is_operational = TrainingProgram.TrainingType.OPERATIONAL in form.cleaned_data["training_types"]
            item.is_active = payload["is_active"]
            item.save()
            item.expense_items.set(selected_ids)
        elif operation == "toggle":
            item.is_active = payload["is_active"]
            item.version += 1
            item.save(update_fields=["is_active", "version", "updated_at"])
        else:
            item.delete()  # Cascades links only; shared expense-item records remain intact.


@login_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def index(request):
    name = request.user.get_short_name() or request.user.get_username()
    add_snapshot = _sign({"operation": "add"}, request.user)
    context = {"page_heading": "إدارة برامج التدريب", "active_page": "training_programs", "display_name": name,
               "avatar_initial": name[:1], "add_snapshot": add_snapshot,
               "editor_form": TrainingProgramForm(initial={"operation": "add", "snapshot": add_snapshot, "is_active": "1", "training_types": "training"})}
    status = 200
    try:
        if request.method == "POST":
            action = request.POST.get("action")
            if action == "preview":
                snapshot = _load(request.POST.get("snapshot"), request.user)
                operation = snapshot["operation"]
                item = None
                if operation != "add":
                    item = TrainingProgram.objects.prefetch_related("expense_items").filter(pk=snapshot.get("id")).first()
                    if not _unchanged(item, snapshot):
                        raise ProgramConflict(_stale())
                if operation in {"add", "edit"}:
                    if request.POST.get("operation") != operation:
                        raise signing.BadSignature("Operation changed")
                    form = TrainingProgramForm(request.POST, instance_id=item.pk if item else None)
                    if form.is_valid():
                        values = {key: form.cleaned_data[key] for key in ["name", "category", "training_types"]}
                        values["is_active"] = form.cleaned_data["is_active"] == "1"
                        selected = list(form.cleaned_data["expense_items"])
                        if item and values == _values(item) and set(s.pk for s in selected) == set(s.pk for s in item.expense_items.all()):
                            context["notice"] = "لم يتم إجراء أي تغييرات على البرنامج."
                        else:
                            context["pending"] = _pending(operation, item, values, selected, request.user)
                    else:
                        context.update(editor_form=form, editing=True, editor_operation=operation)
                        status = 400
                else:
                    values = _values(item)
                    if operation == "toggle":
                        values["is_active"] = not item.is_active
                    context["pending"] = _pending(operation, item, values, list(item.expense_items.all()), request.user)
            elif action == "confirm":
                payload = _load(request.POST.get("token"), request.user, CONFIRM_SALT)
                _apply(payload)
                message = {"add": "تمت إضافة البرنامج بنجاح.", "edit": "تم تعديل البرنامج بنجاح.", "delete": "تم حذف البرنامج مع الاحتفاظ ببنود الصرف.", "toggle": "تم تحديث حالة البرنامج بنجاح."}[payload["operation"]]
                messages.success(request, message)
                return add_login_headers(_makken_settings_redirect(request, "training_programs:index"))
            else:
                context["error"], status = "طلب غير صالح. لم يتم تغيير السجلات.", 400
        else:
            edit = request.GET.get("edit")
            if edit == "new":
                context.update(editing=True, editor_operation="add")
            elif edit:
                item = TrainingProgram.objects.prefetch_related("expense_items").filter(pk=int(edit)).first() if edit.isascii() and edit.isdecimal() and len(edit) <= 18 else None
                if item:
                    initial = {**_values(item), "operation": "edit", "snapshot": _snapshot(item, "edit", request.user),
                               "is_active": "1" if item.is_active else "0", "training_types": item.training_types[0], "expense_items": [s.pk for s in item.expense_items.all()]}
                    context.update(editing=True, editor_operation="edit", editor_form=TrainingProgramForm(instance_id=item.pk, initial=initial))
                else:
                    context["error"], status = "البرنامج المطلوب غير موجود.", 404
    except DependencyBlocked as exc:
        context.update(blocked_context(exc))
        status = 409
    except signing.BadSignature:
        context["error"], status = "انتهت صلاحية الطلب أو تغيّر محتواه. أعد فتح الصفحة وحاول مجددًا.", 400
    except ProgramConflict as exc:
        context["error"], status = str(exc), 409
    except (IntegrityError, ProtectedError, RestrictedError):
        context["error"], status = "تعذّر تنفيذ الطلب. الاسم مستخدم بالفعل أو تغيّرت البيانات. لم يُحفظ أي تغيير.", 409
    page = Paginator(_makken_settings_apply(request, TrainingProgram.objects.prefetch_related("expense_items").all()), 10).get_page(request.GET.get("page"))
    rows = []
    for item in page:
        rows.append({"id": item.pk, "name": item.name, "is_active": item.is_active, "category_label": item.get_category_display(),
                     "type_labels": item.training_type_labels, "expense_items": list(item.expense_items.all()),
                     "toggle_snapshot": _snapshot(item, "toggle", request.user), "delete_snapshot": _snapshot(item, "delete", request.user)})
    context.update(rows=rows, page_obj=page)
    # MAKKEN SETTINGS FILTER CONTEXT
    context.update(_makken_settings_context(request))
    return add_login_headers(render(request, "training_programs/index.html", context, status=status))
