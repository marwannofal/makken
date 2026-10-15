from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from accounts.security import add_login_headers
from .forms import ColorChangeForm
from .models import DevelopmentState, StateColor

TITLE = "حالة تطور المنظمات للرعاية"
SNAPSHOT_SALT = "makken.care-states.snapshot.v1"
CONFIRM_SALT = "makken.care-states.confirm.v1"
TOKEN_AGE = 20 * 60


def _rows(user):
    colors = {item.state: item for item in StateColor.objects.all()}
    rows = []
    for state in DevelopmentState:
        item = colors[state.value]
        snapshot = signing.dumps({"state": state.value, "color": item.color, "version": item.version, "user": str(user.pk)}, salt=SNAPSHOT_SALT)
        rows.append({"state": state.value, "label": state.label, "color": item.color, "version": item.version, "snapshot": snapshot})
    return rows


def _load_token(value, salt, user):
    if not isinstance(value, str) or len(value) > 2048:
        raise signing.BadSignature("Invalid token")
    payload = signing.loads(value, salt=salt, max_age=TOKEN_AGE)
    if not isinstance(payload, dict) or payload.get("user") != str(user.pk) or payload.get("state") not in DevelopmentState.values:
        raise signing.BadSignature("Invalid token")
    return payload


@login_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def index(request):
    name = request.user.get_short_name() or request.user.get_username()
    rows = _rows(request.user)
    context = {"rows": rows, "page_heading": TITLE, "active_page": "care_states", "display_name": name, "avatar_initial": name[:1]}
    status = 200
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "preview":
            form = ColorChangeForm(request.POST)
            if form.is_valid():
                try:
                    snapshot = _load_token(form.cleaned_data["snapshot"], SNAPSHOT_SALT, request.user)
                    row = next(r for r in rows if r["state"] == form.cleaned_data["state"])
                    if snapshot["state"] != row["state"]:
                        raise signing.BadSignature("Different state")
                    if snapshot.get("version") != row["version"] or snapshot.get("color") != row["color"]:
                        context["error"] = "تغيّر اللون بواسطة مستخدم آخر. راجع اللون الحالي وحاول مجددًا."
                        status = 409
                    elif form.cleaned_data["color"] == row["color"].upper():
                        context["notice"] = "لم يتغيّر اللون. اختر لونًا مختلفًا للتعديل."
                    else:
                        payload = {**snapshot, "new_color": form.cleaned_data["color"]}
                        context["pending"] = {"label": row["label"], "old_color": row["color"], "new_color": payload["new_color"], "token": signing.dumps(payload, salt=CONFIRM_SALT)}
                except (signing.BadSignature, KeyError):
                    context["error"] = "انتهت صلاحية الطلب أو تغيّر محتواه. أعد اختيار اللون وحاول مجددًا."
                    status = 400
            else:
                context["error"] = "تعذّر مراجعة التعديل. اختر حالة صحيحة ولونًا بصيغة #24B3AF."
                status = 400
        elif action == "confirm":
            try:
                payload = _load_token(request.POST.get("token"), CONFIRM_SALT, request.user)
                validation = ColorChangeForm({"state": payload["state"], "color": payload.get("new_color"), "snapshot": "validated"})
                if not validation.is_valid():
                    raise signing.BadSignature("Invalid color")
                # Lock and compare the exact version shown in the confirmation.
                # Replays and concurrent edits cannot silently overwrite newer colors.
                with transaction.atomic():
                    item = StateColor.objects.select_for_update().get(state=payload["state"])
                    if item.version != payload.get("version") or item.color != payload.get("color"):
                        context["error"] = "تغيّر اللون أو تم حفظ هذا التعديل مسبقًا. راجع اللون الحالي وحاول مجددًا."
                        status = 409
                    else:
                        updated = StateColor.objects.filter(state=item.state, version=item.version).update(color=validation.cleaned_data["color"], version=item.version + 1, updated_at=timezone.now())
                        if updated != 1:
                            context["error"] = "تغيّر اللون بواسطة مستخدم آخر. أعد المحاولة."
                            status = 409
                        else:
                            messages.success(request, f"تم تحديث لون حالة «{item.get_state_display()}» بنجاح.")
                            return add_login_headers(redirect("care_states:index"))
            except (signing.BadSignature, StateColor.DoesNotExist, KeyError):
                context["error"] = "انتهت صلاحية التأكيد أو تغيّر محتواه. أعد اختيار اللون وحاول مجددًا."
                status = 400
            context["rows"] = _rows(request.user)
        else:
            context["error"] = "طلب غير صالح. لم يتم تغيير الألوان."
            status = 400
    else:
        edit = request.GET.get("edit")
        context["editing"] = next((row for row in rows if row["state"] == edit), None)
    return add_login_headers(render(request, "care_states/index.html", context, status=status))
