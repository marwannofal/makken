from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError, RestrictedError
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from accounts.security import add_login_headers
from .forms import EntityForm
from .models import Entity, EntityType, EntityBranch

SNAPSHOT_SALT = "makken.entities.snapshot.v1"
CONFIRM_SALT = "makken.entities.confirm.v1"
TOKEN_AGE = 20 * 60
OPERATIONS = {"add", "edit", "delete", "toggle"}


def _sign(payload, user, salt=SNAPSHOT_SALT):
    return signing.dumps({**payload, "user": str(user.pk)}, salt=salt)


def _load(token, user, salt=SNAPSHOT_SALT):
    if not isinstance(token, str) or len(token) > 4096:
        raise signing.BadSignature("Invalid token")
    payload = signing.loads(token, salt=salt, max_age=TOKEN_AGE)
    if not isinstance(payload, dict) or payload.get("user") != str(user.pk) or payload.get("operation") not in OPERATIONS:
        raise signing.BadSignature("Invalid token")
    return payload


def _snapshot(item, operation, user):
    return _sign({"operation": operation, "id": item.pk, "version": item.version}, user)


def _form_data(form):
    return {"name": form.cleaned_data["name"], "entity_type": form.cleaned_data["entity_type"], "branch": form.cleaned_data["branch"], "is_active": form.cleaned_data["is_active"] == "1"}


def _item_data(item):
    return {"name": item.name, "entity_type": item.entity_type, "branch": item.branch, "is_active": item.is_active}


def _pending(operation, item, data, user):
    payload = {"operation": operation, "id": item.pk if item else None, "version": item.version if item else None, **data}
    titles = {"add": "تأكيد إضافة الكيان", "edit": "تأكيد تعديل الكيان", "delete": "تأكيد حذف الكيان", "toggle": "تأكيد تغيير حالة الكيان"}
    buttons = {"add": "تأكيد الإضافة", "edit": "تأكيد التعديل", "delete": "نعم، حذف الكيان", "toggle": "تأكيد التغيير"}
    old = _item_data(item) if item else {}
    labels = {"name": "اسم الكيان", "entity_type": "الكيان", "branch": "فرع الكيان", "is_active": "حالة السجل"}
    def display(key, value):
        if key == "entity_type":
            return EntityType(value).label
        if key == "branch":
            return EntityBranch(value).label if value else "لا ينطبق"
        if key == "is_active":
            return "نشط" if value else "غير نشط"
        return value
    fields = []
    for key in labels:
        if key == "branch" and not data["branch"]:
            continue
        fields.append({"label": labels[key], "value": display(key, data[key]), "changed": bool(item and old[key] != data[key]), "old": display(key, old[key]) if item else ""})
    return {**payload, "fields": fields, "clears_branch": bool(item and item.branch and not data["branch"]), "title": titles[operation], "button": buttons[operation], "token": _sign(payload, user, CONFIRM_SALT)}


def _stale():
    return "تغيّر هذا الكيان أو حُذف، أو تم تنفيذ الطلب مسبقًا. راجع القائمة وحاول مجددًا."


@login_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def index(request):
    name = request.user.get_short_name() or request.user.get_username()
    add_snapshot = _sign({"operation": "add"}, request.user)
    context = {"page_heading": "إدارة الكيانات", "active_page": "entities", "display_name": name, "avatar_initial": name[:1], "add_snapshot": add_snapshot}
    context["editor_form"] = EntityForm(initial={"operation": "add", "snapshot": add_snapshot, "entity_type": EntityType.GOVERNMENT, "is_active": "1"})
    status = 200
    try:
        if request.method == "POST":
            action = request.POST.get("action")
            if action == "preview":
                snapshot = _load(request.POST.get("snapshot"), request.user)
                operation = snapshot["operation"]
                item = None
                if operation != "add":
                    item = Entity.objects.filter(pk=snapshot.get("id")).first()
                    if item is None or item.version != snapshot.get("version"):
                        context["error"], status = _stale(), 409
                if status == 200:
                    if operation in {"add", "edit"}:
                        form = EntityForm(request.POST, instance_id=item.pk if item else None)
                        if request.POST.get("operation") != operation:
                            raise signing.BadSignature("Operation changed")
                        if form.is_valid():
                            data = _form_data(form)
                            if item and _item_data(item) == data:
                                context["notice"] = "لم يتم إجراء أي تغييرات على الكيان."
                            else:
                                context["pending"] = _pending(operation, item, data, request.user)
                        else:
                            context.update(editor_form=form, editing=True, editor_operation=operation)
                            status = 400
                    else:
                        data = _item_data(item)
                        if operation == "toggle":
                            data["is_active"] = not item.is_active
                        context["pending"] = _pending(operation, item, data, request.user)
            elif action == "confirm":
                payload = _load(request.POST.get("token"), request.user, CONFIRM_SALT)
                operation = payload["operation"]
                if not isinstance(payload.get("name"), str) or type(payload.get("is_active")) is not bool:
                    raise signing.BadSignature("Invalid confirmation")
                with transaction.atomic():
                    item = None
                    if operation != "add":
                        item = Entity.objects.select_for_update().filter(pk=payload.get("id")).first()
                        if item is None or item.version != payload.get("version"):
                            context["error"], status = _stale(), 409
                    if status == 200:
                        if operation in {"add", "edit"}:
                            form = EntityForm({"operation": operation, "name": payload["name"], "entity_type": payload.get("entity_type"), "branch": payload.get("branch", ""), "is_active": "1" if payload["is_active"] else "0", "snapshot": "validated"}, instance_id=item.pk if item else None)
                            if not form.is_valid():
                                context["error"], status = "تعذّر الحفظ. قد يكون الاسم مستخدمًا بالفعل. أعد فتح النموذج وراجع البيانات.", 409
                            elif operation == "add":
                                Entity.objects.create(**_form_data(form))
                            else:
                                for key, value in _form_data(form).items():
                                    setattr(item, key, value)
                                item.version += 1
                                item.save()
                        elif operation == "toggle":
                            item.is_active = payload["is_active"]
                            item.version += 1
                            item.save(update_fields=["is_active", "version", "updated_at"])
                        else:
                            item.delete()
                if status == 200:
                    message = {"add": "تمت إضافة الكيان بنجاح.", "edit": "تم تعديل الكيان بنجاح.", "delete": "تم حذف الكيان بنجاح.", "toggle": "تم تحديث حالة الكيان بنجاح."}[operation]
                    messages.success(request, message)
                    return add_login_headers(redirect("entities:index"))
            else:
                context["error"], status = "طلب غير صالح. لم يتم تغيير السجلات.", 400
        else:
            edit = request.GET.get("edit")
            if edit == "new":
                context.update(editing=True, editor_operation="add")
            elif edit:
                item = Entity.objects.filter(pk=int(edit)).first() if edit.isascii() and edit.isdecimal() and len(edit) <= 18 else None
                if item:
                    context.update(editing=True, editor_operation="edit", editor_form=EntityForm(initial={"operation": "edit", "snapshot": _snapshot(item, "edit", request.user), **_item_data(item), "is_active": "1" if item.is_active else "0"}))
                else:
                    context["error"], status = "الكيان المطلوب غير موجود.", 404
    except signing.BadSignature:
        context["error"], status = "انتهت صلاحية الطلب أو تغيّر محتواه. أعد فتح الصفحة وحاول مجددًا.", 400
    except (IntegrityError, ProtectedError, RestrictedError):
        context["error"], status = "تعذّر تنفيذ الطلب. الاسم مستخدم بالفعل أو الكيان مرتبط بسجلات أخرى. راجع القائمة وحاول مجددًا.", 409
    page = Paginator(Entity.objects.all(), 15).get_page(request.GET.get("page"))
    rows = []
    for item in page:
        rows.append({"id": item.pk, **_item_data(item), "kind_label": item.get_entity_type_display(), "branch_label": item.get_branch_display() if item.branch else "—", "edit_snapshot": _snapshot(item, "edit", request.user), "toggle_snapshot": _snapshot(item, "toggle", request.user), "delete_snapshot": _snapshot(item, "delete", request.user)})
    context.update(rows=rows, page_obj=page)
    return add_login_headers(render(request, "entities/index.html", context, status=status))
