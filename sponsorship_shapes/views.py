from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError, RestrictedError
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from accounts.security import add_login_headers
from .forms import SponsorshipShapeForm
from .models import SponsorshipShape

SNAPSHOT_SALT = "makken.sponsorship_shapes.snapshot.v1"
CONFIRM_SALT = "makken.sponsorship_shapes.confirm.v1"
TOKEN_AGE = 20 * 60
OPERATIONS = {"add", "edit", "delete", "toggle"}


def _sign(payload, user, salt=SNAPSHOT_SALT):
    return signing.dumps({**payload, "user": str(user.pk)}, salt=salt, compress=True)


def _load(token, user, salt=SNAPSHOT_SALT):
    if not isinstance(token, str) or len(token) > 65536:
        raise signing.BadSignature("Invalid token")
    payload = signing.loads(token, salt=salt, max_age=TOKEN_AGE)
    if not isinstance(payload, dict) or payload.get("user") != str(user.pk) or payload.get("operation") not in OPERATIONS:
        raise signing.BadSignature("Invalid token")
    return payload


def _snapshot(item, operation, user):
    return _sign({"operation": operation, "id": item.pk, "version": item.version}, user)


def _pending(operation, item, name, description, employment, active, user):
    payload = {"operation": operation, "id": item.pk if item else None, "version": item.version if item else None, "name": name, "description": description, "is_employment": employment, "is_active": active}
    titles = {"add": "تأكيد إضافة شكل الرعاية", "edit": "تأكيد تعديل شكل الرعاية", "delete": "تأكيد حذف شكل الرعاية", "toggle": "تأكيد تغيير حالة شكل الرعاية"}
    buttons = {"add": "تأكيد الإضافة", "edit": "تأكيد التعديل", "delete": "نعم، حذف شكل الرعاية", "toggle": "تأكيد التغيير"}
    return {**payload, "old_name": item.name if item else None, "old_description": item.description if item else None, "old_employment": item.is_employment if item else None, "old_active": item.is_active if item else None, "title": titles[operation], "button": buttons[operation], "token": _sign(payload, user, CONFIRM_SALT)}


def _stale():
    return "تغيّر هذا الشكل أو حُذف، أو تم تنفيذ الطلب مسبقًا. راجع القائمة وحاول مجددًا."


@login_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def index(request):
    name = request.user.get_short_name() or request.user.get_username()
    add_snapshot = _sign({"operation": "add"}, request.user)
    context = {"page_heading": "إدارة أشكال الرعاية", "active_page": "sponsorship_shapes", "display_name": name, "avatar_initial": name[:1], "add_snapshot": add_snapshot}
    context["editor_form"] = SponsorshipShapeForm(initial={"operation": "add", "snapshot": add_snapshot, "is_active": "1", "is_employment": "0"})
    status = 200
    try:
        if request.method == "POST":
            action = request.POST.get("action")
            if action == "preview":
                snapshot = _load(request.POST.get("snapshot"), request.user)
                operation = snapshot["operation"]
                item = None
                if operation != "add":
                    item = SponsorshipShape.objects.filter(pk=snapshot.get("id")).first()
                    if item is None or item.version != snapshot.get("version"):
                        context["error"], status = _stale(), 409
                if status == 200:
                    if operation in {"add", "edit"}:
                        form = SponsorshipShapeForm(request.POST, instance_id=item.pk if item else None)
                        if request.POST.get("operation") != operation:
                            raise signing.BadSignature("Operation changed")
                        if form.is_valid():
                            new_name, active = form.cleaned_data["name"], form.cleaned_data["is_active"] == "1"
                            description, employment = form.cleaned_data["description"], form.cleaned_data["is_employment"] == "1"
                            if item and item.name == new_name and item.description == description and item.is_employment == employment and item.is_active == active:
                                context["notice"] = "لم يتم إجراء أي تغييرات على الشكل."
                            else:
                                context["pending"] = _pending(operation, item, new_name, description, employment, active, request.user)
                        else:
                            context.update(editor_form=form, editing=True, editor_operation=operation)
                            status = 400
                    else:
                        active = not item.is_active if operation == "toggle" else item.is_active
                        context["pending"] = _pending(operation, item, item.name, item.description, item.is_employment, active, request.user)
            elif action == "confirm":
                payload = _load(request.POST.get("token"), request.user, CONFIRM_SALT)
                operation = payload["operation"]
                if not isinstance(payload.get("name"), str) or not isinstance(payload.get("description"), str) or type(payload.get("is_employment")) is not bool or type(payload.get("is_active")) is not bool:
                    raise signing.BadSignature("Invalid confirmation")
                with transaction.atomic():
                    item = None
                    if operation != "add":
                        item = SponsorshipShape.objects.select_for_update().filter(pk=payload.get("id")).first()
                        if item is None or item.version != payload.get("version"):
                            context["error"], status = _stale(), 409
                    if status == 200:
                        if operation in {"add", "edit"}:
                            form = SponsorshipShapeForm({"operation": operation, "name": payload["name"], "description": payload["description"], "is_employment": "1" if payload["is_employment"] else "0", "is_active": "1" if payload["is_active"] else "0", "snapshot": "validated"}, instance_id=item.pk if item else None)
                            if not form.is_valid():
                                context["error"], status = "تعذّر الحفظ. قد يكون الاسم مستخدمًا بالفعل. أعد فتح النموذج وراجع البيانات.", 409
                            elif operation == "add":
                                SponsorshipShape.objects.create(name=form.cleaned_data["name"], description=form.cleaned_data["description"], is_employment=payload["is_employment"], is_active=payload["is_active"])
                            else:
                                item.name, item.is_active = form.cleaned_data["name"], payload["is_active"]
                                item.description, item.is_employment = form.cleaned_data["description"], payload["is_employment"]
                                item.version += 1
                                item.save()
                        elif operation == "toggle":
                            item.is_active = payload["is_active"]
                            item.version += 1
                            item.save(update_fields=["is_active", "version", "updated_at"])
                        else:
                            item.delete()
                if status == 200:
                    message = {"add": "تمت إضافة شكل الرعاية بنجاح.", "edit": "تم تعديل شكل الرعاية بنجاح.", "delete": "تم حذف شكل الرعاية بنجاح.", "toggle": "تم تحديث حالة شكل الرعاية بنجاح."}[operation]
                    messages.success(request, message)
                    return add_login_headers(redirect("sponsorship_shapes:index"))
            else:
                context["error"], status = "طلب غير صالح. لم يتم تغيير السجلات.", 400
        else:
            edit = request.GET.get("edit")
            if edit == "new":
                context.update(editing=True, editor_operation="add")
            elif edit:
                item = SponsorshipShape.objects.filter(pk=int(edit)).first() if edit.isascii() and edit.isdecimal() and len(edit) <= 18 else None
                if item:
                    context.update(editing=True, editor_operation="edit", editor_form=SponsorshipShapeForm(initial={"operation": "edit", "snapshot": _snapshot(item, "edit", request.user), "name": item.name, "description": item.description, "is_employment": "1" if item.is_employment else "0", "is_active": "1" if item.is_active else "0"}))
                else:
                    context["error"], status = "شكل الرعاية المطلوب غير موجود.", 404
    except signing.BadSignature:
        context["error"], status = "انتهت صلاحية الطلب أو تغيّر محتواه. أعد فتح الصفحة وحاول مجددًا.", 400
    except (IntegrityError, ProtectedError, RestrictedError):
        context["error"], status = "تعذّر تنفيذ الطلب. الاسم مستخدم بالفعل أو شكل الرعاية مرتبط بسجلات أخرى. راجع القائمة وحاول مجددًا.", 409
    page = Paginator(SponsorshipShape.objects.all(), 10).get_page(request.GET.get("page"))
    rows = []
    for item in page:
        rows.append({"id": item.pk, "name": item.name, "description": item.description, "is_employment": item.is_employment, "is_active": item.is_active, "edit_snapshot": _snapshot(item, "edit", request.user), "toggle_snapshot": _snapshot(item, "toggle", request.user), "delete_snapshot": _snapshot(item, "delete", request.user)})
    context.update(rows=rows, page_obj=page)
    return add_login_headers(render(request, "sponsorship_shapes/index.html", context, status=status))
