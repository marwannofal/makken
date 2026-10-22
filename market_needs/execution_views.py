import json
import uuid
from urllib.parse import urlencode
from django.contrib import messages
from django.core import signing
from django.core.paginator import Paginator
from django.db import IntegrityError, OperationalError
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods
from access_control.enforcement import module_view
from access_control.policy import for_request
from accounts.security import add_login_headers
from service_providers.models import ServiceProvider
from .models import NeedExecution, ExecutionStatus
from .execution_forms import ExecutionForm
from . import execution_matching as matching
from .execution_services import ExecutionConflict, save_execution, validate_selection
from .views import base, funding_details, sponsorship_query

SALT = "makken.execution.20261021"


def signed(request, need, execution, kind="editor", **extra):
    return signing.dumps({"user": request.user.pk, "need": need.pk, "need_version": need.version,
                          "version": execution.version if execution else 0, "nonce": str(uuid.uuid4()),
                          "kind": kind, **extra}, salt=SALT, compress=True)


def load_snapshot(request, pk):
    action = request.POST.get("action")
    if action not in {"preview", "confirm"}:
        raise signing.BadSignature
    raw = request.POST.get("snapshot", "")
    if len(raw) > 22000:
        raise signing.BadSignature
    data = signing.loads(raw, salt=SALT, max_age=1200)
    if not isinstance(data, dict) or data.get("user") != request.user.pk or data.get("need") != pk or data.get("kind") != ("editor" if action == "preview" else "confirm"):
        raise signing.BadSignature
    return data


def mutation_permissions(request, pk):
    payload = load_snapshot(request, pk)
    execution = NeedExecution.objects.filter(need_id=pk).first()
    needed = ["edit" if execution else "create"]
    requested = request.POST.get("status") if request.POST.get("action") == "preview" else payload.get("proposal", {}).get("status")
    if requested != (execution.status if execution else ExecutionStatus.NEW):
        needed.append("change_status")
    return needed


def pagination(request, key, page):
    params = request.GET.copy()
    for name in (key, "detail", "candidate", "kind", "_mk_export", "_mk_table"):
        params.pop(name, None)
    def url(number):
        copy = params.copy(); copy[key] = str(number)
        return "?" + copy.urlencode()
    return {"key": key, "page": page, "previous": url(page.previous_page_number()) if page.has_previous() else "",
            "next": url(page.next_page_number()) if page.has_next() else ""}


def list_context(request, assignment=False):
    context = base(request, "اختيار بطاقة لإدارة تنفيذ البرنامج" if assignment else "البرامج المعتمدة وفقًا للتخصص", "provider_assignments" if assignment else "approved_programs")
    items = matching.approved_needs()
    q, state = request.GET.get("q", "").strip()[:200], request.GET.get("status", "")
    if state in ExecutionStatus.values:
        items = items.filter(Q(execution__status=state) | (Q(execution__isnull=True) if state == "new" else Q(pk__in=[])))
    for word in q.split()[:12]:
        condition = Q(title__icontains=word) | Q(sector__name__icontains=word) | Q(specialization__name__icontains=word) | Q(program_name__icontains=word) | Q(regions__name__icontains=word) | Q(training_type__icontains=word)
        labels = [key for key, label in ExecutionStatus.choices if word in label]
        condition |= Q(execution__status__in=labels)
        if "new" in labels:
            condition |= Q(execution__isnull=True)
        if word in {"تحالف", "فردي"}:
            condition |= Q(approved_count__gt=1) if word == "تحالف" else Q(approved_count=1)
        if word in {"مكتمل", "مكتملة", "الدعم", "الرعاية"}:
            condition |= Q(status="complete")
        from partnerships.financial import MoneyField
        from django import forms
        try:
            value = MoneyField().clean(word)
            condition |= Q(total_cost=value)
            if value == value.to_integral_value():
                condition |= Q(beneficiaries=int(value))
        except forms.ValidationError:
            pass
        items = items.filter(condition)
    page = Paginator(items.distinct().order_by("-pk"), 15).get_page(request.GET.get("page"))
    for item in page:
        item.execution_permission = "edit" if hasattr(item, "execution") else "create"
    detail = None
    if request.GET.get("detail"):
        detail = get_object_or_404(matching.approved_needs().prefetch_related("expense_lines__expense_item", "expense_lines__sponsorship_shape"), pk=request.GET["detail"]) if request.GET["detail"].isascii() and request.GET["detail"].isdigit() else None
        if detail is None:
            raise Http404
        funding_details(detail)
        context["history_page"] = Paginator(detail.events.select_related("actor"), 20).get_page(request.GET.get("history_page"))
        params = request.GET.copy(); params.pop("history_page", None)
        context["history_query"] = params.urlencode()
    context.update(page_obj=page, pager=pagination(request, "page", page), q=q, selected_state=state,
                   state_choices=ExecutionStatus.choices, detail=detail, assignment_list=assignment,
                   filter_query=urlencode({"q": q, "status": state}))
    return context


@module_view("approved_programs")
@require_GET
def index(request):
    return add_login_headers(render(request, "market_needs/execution/index.html", list_context(request)))


@module_view("provider_assignments")
@require_GET
def assignments(request):
    return add_login_headers(render(request, "market_needs/execution/index.html", list_context(request, True)))


@module_view("provider_assignments")
@require_http_methods(["GET", "POST"])
def assignment(request, pk):
    need = get_object_or_404(matching.approved_needs(), pk=pk)
    execution = NeedExecution.objects.filter(need=need).first()
    policy = for_request(request)
    operation = "edit" if execution else "create"
    writable = need.is_active and (not execution or execution.status != "complete") and policy.can("provider_assignments", operation)
    selected_p = list(execution.provider_links.values_list("provider_id", flat=True)) if execution else []
    selected_e = list(execution.employer_links.values_list("partnership_id", flat=True)) if execution else []
    initial = {"status": execution.status if execution else "new", "notes": execution.notes if execution else "",
               "selection": json.dumps({"providers": selected_p, "employers": selected_e})}
    form = ExecutionForm(initial=initial)
    context = base(request, "اختيار مزود خدمة", "provider_assignments")
    status_code, pending = 200, None
    snapshot = signed(request, need, execution)
    if request.method == "POST":
        try:
            if int(request.META.get("CONTENT_LENGTH") or 0) > 60000:
                raise signing.BadSignature
            payload = load_snapshot(request, pk)
            if request.POST["action"] == "confirm":
                proposal = payload["proposal"]
                saved = save_execution(need_id=pk, expected_version=payload["version"], expected_need_version=payload["need_version"], nonce=payload["nonce"], data=proposal, actor=request.user)
                messages.success(request, "تم حفظ بيانات التنفيذ بنجاح." + (" اكتمل التنفيذ وأُغلق التعديل." if saved.status == "complete" else ""))
                return add_login_headers(redirect("program_execution:assignment", pk=pk))
            snapshot = request.POST["snapshot"]
            form = ExecutionForm(request.POST)
            if not writable:
                raise ExecutionConflict("لا يمكن تعديل هذا السجل؛ قد يكون التنفيذ مكتملًا أو البطاقة غير نشطة.")
            if payload["version"] != (execution.version if execution else 0) or payload["need_version"] != need.version:
                raise ExecutionConflict("تغيّرت البيانات منذ فتح النموذج. حدّث الصفحة.")
            if form.is_valid():
                proposal = form.proposal()
                validate_selection(need, proposal["status"], proposal["providers"], proposal["employers"], selected_p, selected_e)
                pending = {"providers": len(proposal["providers"]), "employers": len(proposal["employers"]),
                           "status": ExecutionStatus(proposal["status"]).label,
                           "completing": proposal["status"] == "complete",
                           "snapshot": signing.dumps({**payload, "kind": "confirm", "proposal": proposal}, salt=SALT, compress=True)}
            else:
                status_code = 400
        except (signing.BadSignature, KeyError, TypeError, ValueError):
            context["error"], status_code = "انتهت صلاحية النموذج أو تعذّر التحقق من الطلب. حدّث الصفحة وحاول مجددًا.", 409
        except ExecutionConflict as error:
            context["error"], status_code = str(error), 409
        except (IntegrityError, OperationalError):
            context["error"], status_code = "حدث تعديل متزامن. حدّث الصفحة؛ لم يُحفظ تغيير جزئي.", 409
    funding_details(need)
    context["funders"] = sponsorship_query(need).filter(status="approved")
    provider_q, employer_q = request.GET.get("provider_q", "").strip()[:200], request.GET.get("employer_q", "").strip()[:200]
    p_query, e_query = matching.providers(need), matching.employers(need)
    for word in provider_q.split()[:12]:
        p_query = p_query.filter(Q(name__icontains=word) | Q(email__icontains=word) | Q(coverage__region__name__icontains=word) | Q(coverage__specializations__name__icontains=word)).distinct()
    for word in employer_q.split()[:12]:
        e_query = e_query.filter(Q(name__icontains=word) | Q(email__icontains=word) | Q(phone__icontains=word) | Q(entity__name__icontains=word) | Q(entity__branch__icontains=word))
    p_page = Paginator(p_query, 10).get_page(request.GET.get("provider_page"))
    e_page = Paginator(e_query, 10).get_page(request.GET.get("employer_page"))
    def candidate_row(item, kind):
        params = request.GET.copy()
        for key in ("candidate", "kind", "_mk_export", "_mk_table"):
            params.pop(key, None)
        params.update({"candidate": item.pk, "kind": kind})
        evidence = matching.provider_evidence(need, item) if kind == "provider" else matching.employer_evidence(need, item)
        return {"item": item, "evidence": evidence, "detail_url": "?" + params.urlencode()}
    p_rows = [candidate_row(item, "provider") for item in p_page]
    e_rows = [candidate_row(item, "employer") for item in e_page]
    selected_rows = []
    if execution:
        selected_rows = [*execution.provider_links.select_related("provider"), *execution.employer_links.select_related("partnership")]
    candidate = None
    raw = request.GET.get("candidate", "")
    if raw.isascii() and raw.isdigit():
        if request.GET.get("kind") == "provider":
            item = matching.providers(need).filter(pk=int(raw)).first()
            if item:
                candidate = {"item": item, "kind": "provider", "evidence": matching.provider_evidence(need, item)}
        elif request.GET.get("kind") == "employer":
            item = matching.employers(need).filter(pk=int(raw)).first()
            if item:
                candidate = {"item": item, "kind": "employer", "evidence": matching.employer_evidence(need, item)}
        if candidate is None:
            raise Http404
    context.update(need=need, execution=execution, writable=writable, form=form, snapshot=snapshot, pending=pending,
                   provider_rows=p_rows, employer_rows=e_rows,
                   provider_pager=pagination(request, "provider_page", p_page), employer_pager=pagination(request, "employer_page", e_page),
                   provider_q=provider_q, employer_q=employer_q, selected_rows=selected_rows,
                   candidate=candidate, selected_p=selected_p, selected_e=selected_e,
                   draft_key=f"makken.execution.{request.user.pk}.{pk}.{execution.version if execution else 0}.{need.version}",
                   incomplete_count=ServiceProvider.objects.filter(is_active=True, program__isnull=True).count())
    context["history_page"] = Paginator(need.events.filter(action__startswith="تنفيذ البرنامج").select_related("actor"), 20).get_page(request.GET.get("history_page"))
    context["execution_history"] = [{"event": event, "before_status": event.before.get("حالة التنفيذ", "لم يُنشأ بعد"), "after_status": event.after.get("حالة التنفيذ"),
        "before_providers": event.before.get("مزودو التدريب", []), "after_providers": event.after.get("مزودو التدريب", []),
        "before_employers": event.before.get("جهات التوظيف", []), "after_employers": event.after.get("جهات التوظيف", []),
        "before_notes": event.before.get("ملاحظات التنفيذ", ""), "after_notes": event.after.get("ملاحظات التنفيذ", "")}
        for event in context["history_page"]]
    context["selection_labels"] = {("providers." + str(row.provider_id) if hasattr(row, "provider_id") else "employers." + str(row.partnership_id)): row.evidence.get("name", "جهة محفوظة") for row in selected_rows}
    history_params = request.GET.copy(); history_params.pop("history_page", None)
    context["history_query"] = history_params.urlencode()
    return_params = {"q": request.GET.get("q", "")[:200], "status": request.GET.get("status", ""), "page": request.GET.get("return_page", "1")}
    context.update(return_q=return_params["q"], return_status=return_params["status"], return_page=return_params["page"])
    context["return_url"] = reverse("program_execution:index" if policy.can("approved_programs") else "program_execution:assignments") + "?" + urlencode(return_params)
    return add_login_headers(render(request, "market_needs/execution/assignment.html", context, status=status_code))
