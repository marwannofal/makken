from access_control.enforcement import module_view, service_operation
# MAKKEN RBAC INTEGRATION v1

from core.dependencies import DependencyBlocked, ensure_allowed, blocked_context
# MAKKEN LINKED RECORD PROTECTION v1
import json
import uuid
from decimal import Decimal
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import RequestDataTooBig, TooManyFilesSent
from django.core.paginator import Paginator
from django.db import IntegrityError, OperationalError
from django.db.models import Count, Q, F, FloatField, Value
from django.db.models.functions import Cast, Round
from django.db.models.deletion import ProtectedError
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_GET

from accounts.security import add_login_headers
from specializations.models import Specialization
from training_programs.models import TrainingProgram
from expense_items.models import ExpenseItem
from sponsorship_shapes.models import SponsorshipShape
from care_states.models import StateColor, DevelopmentState
from .models import Need, NeedStatus, Sponsorship, SponsorshipStatus, SupportAttachment
from .forms import NeedForm, MatchFilterForm, FollowupForm
from .matching import candidates, explain, matching_offerings
from .funding import expense_funding, development_timeline
from . import services

SALT = "makken.market-needs.v2-expense-allocations"
AGE = 20 * 60


def token(request, need=None, operation="save", record=None):
    return signing.dumps({"user": request.user.pk, "id": need.pk if need else None, "version": need.version if need else None,
                          "operation": operation, "record": record.pk if record else None, "record_version": record.version if record else None, "nonce": str(uuid.uuid4())}, salt=SALT, compress=True)


def load_token(request, pk, operations):
    raw = request.POST.get("snapshot", "")
    if len(raw) > 4096:
        raise signing.BadSignature
    data = signing.loads(raw, salt=SALT, max_age=AGE)
    if not isinstance(data, dict) or data.get("user") != request.user.pk or data.get("id") != pk or data.get("operation") not in operations:
        raise signing.BadSignature
    return data


def base(request, heading, active="market_needs"):
    name = request.user.get_short_name() or request.user.get_username()
    return {"page_heading": heading, "active_page": active, "display_name": name, "avatar_initial": name[:1]}


def query():
    return Need.objects.select_related("sector", "specialization", "program").prefetch_related("regions").annotate(approved_count=Count("sponsorships", filter=Q(sponsorships__status=SponsorshipStatus.APPROVED), distinct=True)).order_by("-pk")


def funding_details(need):
    need.funding_lines = expense_funding(need)
    need.allocated_support = sum((line.approved_amount for line in need.funding_lines), Decimal("0.00"))
    need.unallocated_support = need.approved_support - need.allocated_support
    from .models import percentage
    need.allocated_percent = percentage(need.allocated_support, need.total_cost)


def sponsorship_query(need):
    return need.sponsorships.select_related("partnership__development_state", "partnership__entity", "updated_by", "level", "need").prefetch_related(
        "attachments", "allocations__expense_line__expense_item", "partnership__development_history",
    )


def failure(exc):
    if isinstance(exc, services.InvalidForm):
        return "راجع الحقول الموضحة أدناه. لم تُحفظ أي تغييرات.", 400
    if isinstance(exc, signing.BadSignature):
        return "انتهت صلاحية النموذج أو تغيّر محتواه. حدّث الصفحة وحاول مجددًا.", 409
    if isinstance(exc, services.Conflict):
        return str(exc), 409
    return "تعذّر إتمام العملية بسبب تغيير متزامن أو ارتباط قائم. حدّث الصفحة وحاول مجددًا؛ لم يُحفظ تغيير جزئي.", 409


def initial(need):
    if not need:
        return {"lines": "[]", "is_active": "1"}
    data = {name: getattr(need, name) for name in ("title", "description", "duration", "duration_unit", "source", "beneficiaries", "requested_support", "observed_on")}
    data.update(sector=need.sector_id, specialization=need.specialization_id, program=need.program_id,
                regions=list(need.regions.values_list("pk", flat=True)), is_active="1" if need.is_active else "0",
                lines=json.dumps([{"expense": line.expense_item_id, "shape": line.sponsorship_shape_id, "amount": str(line.amount)} for line in need.expense_lines.all()]))
    return data


def catalog(need):
    old_expenses = list(need.expense_lines.values_list("expense_item_id", flat=True)) if need else []
    old_shapes = list(need.expense_lines.values_list("sponsorship_shape_id", flat=True)) if need else []
    programs = TrainingProgram.objects.filter(Q(is_active=True) | Q(pk=need.program_id if need else None)).prefetch_related("expense_items")
    return {
        "specializations": list(Specialization.objects.filter(Q(is_active=True) | Q(pk=need.specialization_id if need else None)).values("id", "name", "sector_id", "is_active")),
        "expenses": list(ExpenseItem.objects.filter(Q(is_active=True) | Q(pk__in=old_expenses)).values("id", "name", "is_active")),
        "shapes": list(SponsorshipShape.objects.filter(Q(is_active=True) | Q(pk__in=old_shapes)).values("id", "name", "is_active")),
        "programs": [{"id": p.pk, "name": p.name, "category": p.get_category_display(), "type": "تدريبي" if p.is_training else "تشغيلي", "expenses": [e.pk for e in p.expense_items.all() if e.is_active]} for p in programs],
        "original_program": need.program_id if need else None, "original_sector": need.sector_id if need else None,
        "old_expenses": old_expenses,
        "funded_program_snapshot": {"category": need.program_category, "type": need.training_type} if need and need.approved_support else None,
    }


@module_view('market_needs')
@login_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def editor(request, pk=None):
    need = get_object_or_404(query(), pk=pk) if pk else None
    context = base(request, "إضافة / تعديل بطاقة حاجة السوق وفقًا للتخصص", "market_need_editor")
    form = NeedForm(initial=initial(need), instance=need)
    snapshot, status = token(request, need), 200
    if request.method == "POST":
        try:
            if len(request.body) > 150000:
                raise signing.BadSignature
            payload = load_token(request, pk, {"save"})
            snapshot = request.POST["snapshot"]
            form = NeedForm(request.POST, instance=need)
            saved = services.save_need(request.POST, request.user, pk, payload["version"], payload["nonce"])
            messages.success(request, "تم حفظ بطاقة حاجة السوق بنجاح.")
            return add_login_headers(redirect("market_needs:followup", pk=saved.pk))
        except DependencyBlocked as exc:
            context.update(blocked_context(exc))
            status = 409
        except (services.Conflict, services.InvalidForm, signing.BadSignature, IntegrityError, ProtectedError, OperationalError) as exc:
            context["error"], status = failure(exc)
            if isinstance(exc, services.InvalidForm):
                form = exc.form
    context.update(need=need, form=form, snapshot=snapshot, catalog=catalog(need))
    return add_login_headers(render(request, "market_needs/editor.html", context, status=status))


@module_view('market_needs')
@login_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def index(request):
    context, status = base(request, "إدارة بطاقات حاجة السوق وفقًا للتخصص"), 200
    if request.method == "POST":
        try:
            raw_pk = request.POST.get("card", "")
            if not raw_pk.isascii() or not raw_pk.isdigit():
                raise signing.BadSignature
            payload = load_token(request, int(raw_pk), {"toggle", "delete"})
            services.card_action(payload["id"], payload["version"], payload["operation"], request.user)
            messages.success(request, "تم تحديث بطاقة الحاجة بنجاح.")
            return add_login_headers(redirect("market_needs:index"))
        except DependencyBlocked as exc:
            context.update(blocked_context(exc))
            status = 409
        except (services.Conflict, signing.BadSignature, IntegrityError, ProtectedError, OperationalError) as exc:
            context["error"], status = failure(exc)
    q, active, state = request.GET.get("q", "").strip()[:200], request.GET.get("active", ""), request.GET.get("state", "")
    items = query().alias(displayed_percent=Round(Cast("approved_support", FloatField()) * Value(100.0) / Cast("total_cost", FloatField()), 2))
    if active in {"1", "0"}:
        items = items.filter(is_active=active == "1")
    if state in NeedStatus.values:
        items = items.filter(status=state)
    for word in q.split()[:12]:
        search = Q(title__icontains=word) | Q(sector__name__icontains=word) | Q(specialization__name__icontains=word) | Q(regions__name__icontains=word) | Q(program_name__icontains=word) | Q(training_type__icontains=word)
        labels = [key for key, label in NeedStatus.choices if word in label]
        search |= Q(status__in=labels)
        if word.replace("MKT-", "").isdigit():
            search |= Q(pk=int(word.replace("MKT-", "")))
        from partnerships.financial import MoneyField
        from django import forms
        try:
            value = MoneyField().clean(word.rstrip("%٪"))
            search |= Q(total_cost=value) | Q(approved_support=value)
            search |= Q(displayed_percent=float(value))
            if value == value.to_integral_value():
                search |= Q(beneficiaries=int(value))
        except DependencyBlocked as exc:
            context.update(blocked_context(exc))
            status = 409
        except forms.ValidationError:
            pass
        if "تحالف" in word:
            search |= Q(approved_count__gt=1)
        if "فردي" in word:
            search |= Q(approved_count=1, approved_support=F("total_cost"))
        if word in {"جزئية", "جزئي"}:
            search |= Q(approved_count=1, approved_support__lt=F("total_cost"))
        if word in {"نشط", "active"}:
            search |= Q(is_active=True)
        if word in {"موقوف", "inactive"}:
            search |= Q(is_active=False)
        items = items.filter(search)
    page = Paginator(items.distinct(), 15).get_page(request.GET.get("page"))
    rows = [{"need": need, "toggle": token(request, need, "toggle"), "delete": token(request, need, "delete")} for need in page]
    detail = None
    if request.GET.get("detail", "").isascii() and request.GET.get("detail", "").isdigit():
        detail = get_object_or_404(query().prefetch_related("expense_lines__expense_item", "expense_lines__sponsorship_shape", "sponsorships__partnership", "sponsorships__attachments"), pk=int(request.GET["detail"]))
        funding_details(detail)
        context["history_page"] = Paginator(detail.events.select_related("actor"), 20).get_page(request.GET.get("history_page"))
        context["history_query"] = urlencode({"q": q, "active": active, "state": state, "page": page.number, "detail": detail.pk})
    context.update(rows=rows, page_obj=page, q=q, selected_active=active, selected_state=state, state_choices=NeedStatus.choices,
                   detail=detail, filter_query=urlencode({"q": q, "active": active, "state": state}))
    return add_login_headers(render(request, "market_needs/index.html", context, status=status))


@module_view('market_needs')
@login_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def followup(request, pk):
    need = get_object_or_404(query().prefetch_related("expense_lines__expense_item", "expense_lines__sponsorship_shape"), pk=pk)
    context, status = base(request, "البحث الذكي: محرك الرعاة المحتملون"), 200
    funding_details(need)
    filters = MatchFilterForm(request.GET)
    valid_filters = filters.is_valid()
    followup_form, selected_record, operation = None, None, ""
    followup_snapshot = ""
    if request.method == "GET" and request.GET.get("operation") in {"notes", "approve", "reject", "allocate", "details"}:
        record_id = request.GET.get("record", "")
        if record_id.isascii() and record_id.isdigit():
            selected_record = get_object_or_404(sponsorship_query(need), pk=int(record_id))
            operation = request.GET["operation"]
            followup_form = FollowupForm(initial={"notes": selected_record.notes}, operation=operation, need=need, record=selected_record)
            followup_snapshot = token(request, need, operation, selected_record)
            context["reopen_followup"] = operation != "details"
    if request.method == "POST":
        try:
            payload = load_token(request, pk, {"add", "notes", "approve", "reject", "allocate"})
            operation = payload["operation"]
            followup_snapshot = request.POST.get("snapshot", "")
            if operation == "add":
                if not valid_filters:
                    raise services.Conflict("معايير البحث غير صالحة.")
                raw_ids = request.POST.getlist("organizations")
                if any(not value.isascii() or not value.isdigit() for value in raw_ids):
                    raise signing.BadSignature
                services.add_candidates(pk, payload["version"], [int(v) for v in raw_ids], filters.cleaned_data, request.user)
            else:
                selected_record = get_object_or_404(Sponsorship.objects.select_related("partnership"), need=need, pk=payload.get("record"))
                services.followup(pk, payload["version"], payload["record"], payload["record_version"], operation, request.POST, request.FILES, request.user)
            messages.success(request, "تم حفظ المتابعة وتحديث حالة الدعم بنجاح.")
            destination = reverse("market_needs:followup", args=[pk])
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return add_login_headers(JsonResponse({"redirect": destination}))
            return add_login_headers(redirect(destination))
        except (services.Conflict, services.InvalidForm, signing.BadSignature, IntegrityError, ProtectedError, OperationalError, OSError, RequestDataTooBig, TooManyFilesSent) as exc:
            context["error"], status = failure(exc)
            if isinstance(exc, services.InvalidForm):
                followup_form = exc.form
                context["reopen_followup"] = True
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                errors = exc.form.errors.get_json_data() if isinstance(exc, services.InvalidForm) else {}
                return add_login_headers(JsonResponse({"error": context["error"], "fields": errors}, status=status))
    if not valid_filters:
        status = 400
    # Search is a read-only GET. It never creates candidates or advances states.
    queryset = candidates(need, filters.cleaned_data) if valid_filters else candidates(need).none()
    page = Paginator(queryset, 10).get_page(request.GET.get("page"))
    record_page = Paginator(sponsorship_query(need), 25).get_page(request.GET.get("followup_page"))
    rows = [{"record": row, "notes_token": token(request, need, "notes", row), "approve_token": token(request, need, "approve", row), "reject_token": token(request, need, "reject", row), "allocate_token": token(request, need, "allocate", row)} for row in record_page]
    shape_map = {}
    for organization_id, shape_id in matching_offerings(need).filter(partnership_id__in=[row["record"].partnership_id for row in rows]).values_list("partnership_id", "sponsorship_shape_id"):
        shape_map.setdefault(organization_id, set()).add(shape_id)
    for row in rows:
        row["allowed_lines"] = ",".join(str(line.pk) for line in need.funding_lines if line.sponsorship_shape_id in shape_map.get(row["record"].partnership_id, set()))
    params = request.GET.copy()
    params.pop("page", None)
    params.pop("record", None)
    params.pop("operation", None)
    context["history_page"] = Paginator(need.events.select_related("actor"), 20).get_page(request.GET.get("history_page"))
    history_params = request.GET.copy()
    history_params.pop("history_page", None)
    context["history_query"] = history_params.urlencode()
    state_colors = StateColor.objects.in_bulk()
    state_options = [{"choice": choice, "state": state_colors.get(choice.data["value"])} for choice in filters["states"]]
    context.update(state_options=state_options, need=need, filter_form=filters, matches=explain(need, page), page_obj=page, records=rows, add_token=token(request, need, "add"),
                   followup_form=followup_form or FollowupForm(need=need), selected_record=selected_record, operation=operation,
                   record_page=record_page, show_record_details=operation == "details" and selected_record is not None,
                   development_history=development_timeline(selected_record.partnership) if selected_record else [],
                   followup_snapshot=followup_snapshot,
                   filter_query=params.urlencode(), upload_limit=getattr(settings, "MAKKEN_SUPPORT_MAX_FILE_SIZE", 100 * 1024 * 1024),
                   upload_max_files=getattr(settings, "MAKKEN_SUPPORT_MAX_FILES", 20))
    return add_login_headers(render(request, "market_needs/followup.html", context, status=status))


@module_view('market_needs')
@login_required(login_url="accounts:login")
@require_GET
def download(request, pk, attachment_id):
    attachment = get_object_or_404(SupportAttachment.objects.select_related("sponsorship"), pk=attachment_id, sponsorship__need_id=pk)
    try:
        source = attachment.file.open("rb")
    except (OSError, ValueError):
        raise Http404
    return add_login_headers(FileResponse(source, as_attachment=True, filename=attachment.original_name, content_type=attachment.content_type))
