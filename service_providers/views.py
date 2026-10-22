from access_control.enforcement import module_view, service_operation
# MAKKEN RBAC INTEGRATION v1

from core.dependencies import DependencyBlocked, ensure_allowed, blocked_context
# MAKKEN LINKED RECORD PROTECTION v1
import json
import uuid
from urllib.parse import urlencode
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Q, Prefetch
from django.db.models.deletion import ProtectedError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from accounts.security import add_login_headers
from partnerships.models import Scope
from training_programs.models import TrainingProgram
from regions.models import Region
from specializations.models import Specialization
from .forms import ProviderForm, coverage_data
from .models import ServiceProvider, ProviderCoverage, ProviderType
from . import services

SALT = "makken.service-providers.v1"
AGE = 20 * 60


def token(data, user):
    return signing.dumps({**data, "user": str(user.pk)}, salt=SALT, compress=True)


def load(value, user, operation):
    if not isinstance(value, str) or len(value) > 160000:
        raise signing.BadSignature
    data = signing.loads(value, salt=SALT, max_age=AGE)
    if not isinstance(data, dict) or data.get("user") != str(user.pk) or data.get("operation") != operation:
        raise signing.BadSignature
    return data


def base(request, title, active):
    name = request.user.get_short_name() or request.user.get_username()
    return {"page_heading": title, "active_page": active, "display_name": name, "avatar_initial": name[:1]}


def query():
    return ServiceProvider.objects.select_related("created_by", "updated_by", "program").prefetch_related("program__expense_items", Prefetch("coverage", queryset=ProviderCoverage.objects.select_related("region").prefetch_related("specializations__sector")))


def catalog(item):
    old = coverage_data(item)
    region_ids = [r["region"] for r in old]
    spec_ids = {s for r in old for s in r["specializations"]}
    programs = TrainingProgram.objects.filter(Q(is_active=True) | Q(pk=item.program_id if item else None)).prefetch_related("expense_items")
    return {"programs": [{"id": p.pk, "category": p.get_category_display(), "type": "تدريبي" if p.is_training else "تشغيلي", "expenses": [e.name for e in p.expense_items.all()]} for p in programs], "regions": list(Region.objects.filter(Q(is_active=True) | Q(pk__in=region_ids)).values("id", "name", "is_active")), "specializations": [{"id": s.pk, "name": s.name, "sector": s.sector.name if s.sector else "", "is_active": bool(s.is_active and s.sector and s.sector.is_active)} for s in Specialization.objects.filter(Q(is_active=True, sector__is_active=True) | Q(pk__in=spec_ids)).select_related("sector")], "original": old}


def initial(item):
    if not item:
        return {"phone_country": "SA", "is_active": "1", "coverage": "[]"}
    return {"program": item.program_id or "", **{name: getattr(item, name) for name in ["name", "representative", "phone_country", "phone", "email", "provider_type", "scope"]}, "is_active": "1" if item.is_active else "0", "coverage": json.dumps(coverage_data(item))}


def list_context(request):
    context = base(request, "إدارة سجل مزودي خدمات التدريب", "service_providers")
    term = request.GET.get("q", "").strip()[:200]
    status = request.GET.get("status", "")
    providers = query()
    if status in {"active", "inactive"}:
        providers = providers.filter(is_active=status == "active")
    if term:
        if term in {"غير نشط", "غير فعال", "inactive"}:
            providers = providers.filter(is_active=False)
        elif term in {"نشط", "فعال", "active"}:
            providers = providers.filter(is_active=True)
        else:
            for word in term.split()[:12]:
                match = Q(name__icontains=word) | Q(representative__icontains=word) | Q(phone__icontains=word) | Q(email__icontains=word) | Q(coverage__region__name__icontains=word) | Q(coverage__specializations__name__icontains=word) | Q(coverage__specializations__sector__name__icontains=word)
                for field, choices in [("provider_type", ProviderType.choices), ("scope", Scope.choices)]:
                    values = [key for key, label in choices if word in label]
                    if values:
                        match |= Q(**{field + "__in": values})
                providers = providers.filter(match)
            providers = providers.distinct()
    page = Paginator(providers, 10).get_page(request.GET.get("page"))
    for item in page:
        item.row_token = token({"operation": "row", "id": item.pk, "version": item.version}, request.user)
        item.specialty_names = list(dict.fromkeys(s.name for row in item.coverage.all() for s in row.specializations.all()))
        item.region_names = list(dict.fromkeys(row.region.name for row in item.coverage.all()))
    context.update(page_obj=page, q=term, selected_status=status, filter_query=urlencode({"q": term, "status": status}), detail=None, pending=None)
    return context


@module_view('service_providers')
@login_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def index(request):
    context, status = list_context(request), 200
    try:
        if request.method == "POST":
            action = request.POST.get("action")
            if action == "preview":
                data = load(request.POST.get("token"), request.user, "row")
                operation = request.POST.get("operation")
                if operation not in {"toggle", "delete"}:
                    raise signing.BadSignature
                item = get_object_or_404(query(), pk=data["id"])
                if item.version != data["version"]:
                    raise services.Conflict("تغيّر السجل. حدّث الصفحة قبل المتابعة.")
                ensure_allowed(item, operation, not item.is_active if operation == "toggle" else None)
                if operation == "delete" and item.converted_partnership_id:
                    raise services.Conflict("لا يمكن حذف مزود مرتبط بسجل الشراكات أو إيقافه قبل معالجة الارتباط.")
                context["pending"] = {"name": item.name, "title": "تأكيد حذف المزود" if operation == "delete" else "تأكيد تغيير حالة السجل", "description": "سيُحذف المزود وبنود مناطقه نهائيًا، مع الاحتفاظ بسجل التغييرات." if operation == "delete" else "سيُحدّث تفعيل سجل المزود غير المستخدم فقط، دون تغيير بيانات المناطق والتخصصات.", "danger": operation == "delete", "token": token({**data, "operation": "row-confirm", "row_operation": operation}, request.user)}
            elif action == "confirm":
                data = load(request.POST.get("token"), request.user, "row-confirm")
                services.row_action({**data, "operation": data["row_operation"]}, request.user)
                messages.success(request, "تم تنفيذ العملية بنجاح.")
                parameters = {"q": request.GET.get("q", "")[:200], "status": request.GET.get("status", ""), "page": request.GET.get("page", "1")}
                return redirect(reverse("service_providers:index") + "?" + urlencode(parameters))
            else:
                raise signing.BadSignature
        detail_id = request.GET.get("detail")
        if detail_id:
            if not detail_id.isdecimal():
                raise Http404
            context["detail"] = get_object_or_404(query(), pk=detail_id)
            context["detail_events"] = context["detail"].events.select_related("actor")[:30]
    except DependencyBlocked as exc:
        context.update(blocked_context(exc))
        status = 409
    except (signing.BadSignature, signing.SignatureExpired):
        context["error"], status = "انتهت صلاحية الطلب أو تعذّر التحقق منه. حدّث الصفحة وحاول مجددًا.", 400
    except (services.Conflict, ProtectedError) as error:
        context["error"], status = str(error) if isinstance(error, services.Conflict) else "هذا السجل مرتبط ببيانات أخرى ولا يمكن حذفه.", 409
    return add_login_headers(render(request, "service_providers/index.html", context, status=status))


@module_view('service_providers')
@login_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def editor(request, pk=None):
    item = get_object_or_404(query(), pk=pk) if pk else None
    context = base(request, "تعديل مزود خدمات التدريب" if item else "إضافة مزود خدمات التدريب", "service_provider_editor")
    editor_token = token({"operation": "editor", "id": pk, "version": item.version if item else None, "nonce": str(uuid.uuid4())}, request.user)
    form, pending, status = ProviderForm(initial=initial(item), instance=item), None, 200
    try:
        if request.method == "POST":
            if int(request.META.get("CONTENT_LENGTH") or 0) > 220000:
                raise signing.BadSignature
            action = request.POST.get("action")
            if action == "preview":
                data = load(request.POST.get("snapshot"), request.user, "editor")
                if data.get("id") != pk or item and data.get("version") != item.version:
                    raise services.Conflict("تغيّر سجل المزود. أعد فتحه قبل التعديل.")
                editor_token = request.POST["snapshot"]
                form = ProviderForm(request.POST, instance=item)
                if form.is_valid():
                    ensure_allowed(item, "edit", form.cleaned_data["is_active"] == "1")
                    values = {name: form.cleaned_data[name] for name in form.fields}
                    values["coverage"] = json.dumps(values["coverage"])
                    pending = {"name": values["name"], "title": "تأكيد حفظ مزود الخدمة", "description": "راجع بيانات المزود والمناطق والتخصصات قبل تأكيد الحفظ.", "token": token({**data, "operation": "save", "data": values}, request.user)}
                else:
                    status = 400
            elif action == "confirm":
                data = load(request.POST.get("token"), request.user, "save")
                if data.get("id") != pk:
                    raise signing.BadSignature
                saved = services.save_provider(data, request.user)
                messages.success(request, "تم حفظ بيانات مزود الخدمة بنجاح.")
                return redirect(reverse("service_providers:index") + "?" + urlencode({"detail": saved.pk}))
            else:
                raise signing.BadSignature
    except DependencyBlocked as exc:
        context.update(blocked_context(exc))
        status = 409
    except (signing.BadSignature, signing.SignatureExpired, ValueError):
        context["error"], status = "انتهت صلاحية الطلب أو تعذّر التحقق منه. أعد فتح النموذج.", 400
    except (services.Conflict, IntegrityError, ProtectedError) as error:
        context["error"], status = str(error) if isinstance(error, services.Conflict) else "تعذّر الحفظ بسبب اسم مكرر أو بيانات مرتبطة تغيّرت. راجع النموذج.", 409
    drafts = form.data.get("coverage", "[]") if form.is_bound else form.initial.get("coverage", "[]")
    try:
        drafts = json.loads(drafts)
        if not isinstance(drafts, list):
            drafts = []
    except DependencyBlocked as exc:
        context.update(blocked_context(exc))
        status = 409
    except (ValueError, TypeError):
        drafts = []
    context.update(item=item, form=form, pending=pending, snapshot=editor_token, catalog=catalog(item), drafts=drafts)
    return add_login_headers(render(request, "service_providers/editor.html", context, status=status))


