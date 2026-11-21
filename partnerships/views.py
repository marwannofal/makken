from pathlib import Path
from access_control.enforcement import module_view, service_operation
# MAKKEN RBAC INTEGRATION v1

from core.dependencies import DependencyBlocked, ensure_allowed, blocked_context
# MAKKEN LINKED RECORD PROTECTION v1
import hashlib
import json
import uuid

import phonenumbers
from django import forms as django_forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q, Prefetch
from django.db.models.deletion import ProtectedError
from django.http import Http404, JsonResponse
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

from .financial import FinancialRange, amount_string, financial_search_clause, financial_redirect
from .development_filter import DevelopmentFilter
from .willingness import WillingnessTransitionForm, save_supporting_files
from .willingness_workflow import (
    PartnershipWorkForm,
    WillingnessDetailsForm,
    apply_willingness_details,
    clause_catalog,
    create_partnership_work,
    details_initial,
    existing_clause_rows,
    existing_team_rows,
    parse_clauses_payload,
    parse_teams_payload,
    save_partnership_clauses,
    save_partnership_departments,
    save_partnership_teams,
    serialize_details,
)
from .attachment_storage import delete_private_files
from access_control.regions import scoped, require_write, regional_transaction
from regions.models import Region

SALT = "makken.partnerships.v2-no-geography"
AGE = 20 * 60


class InvalidWillingnessForm(Exception):
    pass


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


def _query(actor=None):
    return scoped(Partnership.objects.all(), actor).select_related("entity", "development_state", "followup_updated_by").prefetch_related(
        Prefetch("offerings", queryset=PartnershipOffering.objects.select_related("sector", "sponsorship_shape").prefetch_related("specializations")),
        "development_history__state", "willingness_attachments", "administrative_regions")


def _history(item):
    if not item:
        return []
    entered = {entry.state_id: entry.entered_at for entry in item.development_history.all()}
    return [{"label": label, "color": color.color if (color := StateColor.objects.filter(pk=value).first()) else "#74888b", "date": entered.get(value), "current": item.development_state_id == value} for value, label in DevelopmentState.choices]


def _fingerprint(data, lock=False):
    rows = json.loads(data["offerings"])
    selections = [(Region, [int(r.pk) if hasattr(r, "pk") else int(r) for r in data.get("administrative_regions", [])]), (Entity, [int(data["entity"])]), (Sector, sorted({r["sector"] for r in rows})), (Specialization, sorted({s for r in rows for s in r["specializations"]})), (SponsorshipShape, sorted({r["shape"] for r in rows}))]
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
    return {"administrative_regions": [region.pk for region in cleaned["administrative_regions"]], "name": cleaned["name"], "representative": cleaned["representative"], "phone_country": cleaned["phone_country"], "phone": cleaned["phone"], "email": cleaned["email"], "entity_type": cleaned["entity_type"], "entity": str(cleaned["entity"].pk), "scope": cleaned["scope"], "is_active": cleaned["is_active"], "offerings": json.dumps(cleaned["offerings"]), "financial_capacity": amount_string(cleaned["financial_capacity"]),
            "partnership_date": cleaned["partnership_date"], "starts_on": cleaned["starts_on"].isoformat() if cleaned["starts_on"] else "",
            "ends_on": cleaned["ends_on"].isoformat() if cleaned["ends_on"] else ""}


def _initial(item):
    if not item:
        return {"phone_country": "SA", "is_active": "1", "offerings": "[]"}
    return {"administrative_regions": list(item.administrative_regions.values_list("pk", flat=True)), "name": item.name, "representative": item.representative, "phone_country": item.phone_country, "phone": item.phone, "email": item.email, "entity_type": item.entity.entity_type, "entity": item.entity_id, "scope": item.scope, "is_active": "1" if item.is_active else "0", "offerings": json.dumps(offering_data(item)), "financial_capacity": amount_string(item.financial_capacity),
            "partnership_date": item.partnership_date or "", "starts_on": item.starts_on or "", "ends_on": item.ends_on or ""}


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


@service_operation('partnerships', 'save')
def _save(payload, user):
    with transaction.atomic():
        pk = payload.get("id")
        item = Partnership.objects.select_for_update().filter(pk=pk).first() if pk else None
        if pk and (not item or item.version != payload.get("version")):
            raise Conflict("تغيّر السجل أو حُذف منذ فتحه. أعد فتح الصفحة وراجع أحدث البيانات.")
        if not pk:
            repeated = Partnership.objects.filter(request_key=payload["nonce"]).first()
            if repeated:
                require_write(user, repeated)
                return repeated
        data = payload["data"]
        if _fingerprint(data, lock=True) != payload.get("catalog"):
            raise Conflict("تغيّرت بيانات أحد الكيانات أو القطاعات أو التخصصات أو أشكال الرعاية. راجع الاختيارات مجددًا.")
        form = PartnershipForm(data, instance=item, actor=user)
        if not form.is_valid():
            raise Conflict("تعذّر الحفظ. راجع الاسم والبيانات المرتبطة؛ قد تكون تغيّرت منذ المراجعة.")
        clean = form.cleaned_data
        ensure_allowed(item, "edit", clean["is_active"] == "1")
        new = item is None
        initial_state = payload.get("initial_state") or DevelopmentState.CAPABILITY
        if initial_state not in {DevelopmentState.CAPABILITY, DevelopmentState.WILLINGNESS}:
            initial_state = DevelopmentState.CAPABILITY
        if new:
            if not StateColor.objects.filter(pk=initial_state).exists():
                raise Conflict("حالة التطور المحددة غير موجودة. تأكد من تطبيق ترحيلات حالات تطور المنظمات للرعاية.")
            item = Partnership(request_key=payload["nonce"], created_by=user, development_state_id=initial_state)
        for field in ["name", "representative", "phone_country", "phone", "email", "entity", "scope", "financial_capacity", "partnership_date", "starts_on", "ends_on"]:
            setattr(item, field, clean[field])
        item.is_active = clean["is_active"] == "1"
        if not new:
            item.version += 1
        item.save()
        item.administrative_regions.set(clean["administrative_regions"])
        if new:
            DevelopmentHistory.objects.create(partnership=item, state_id=initial_state, entered_at=item.development_state_at)
        item.offerings.all().delete()
        for position, row in enumerate(clean["offerings"]):
            offering = PartnershipOffering.objects.create(partnership=item, sector_id=row["sector"], sponsorship_shape_id=row["shape"], is_active=row["is_active"], position=position)
            offering.specializations.set(row["specializations"])
        if "details" in payload and payload["details"] is not None:
            apply_willingness_details(item, payload["details"])
            item.save()
            save_partnership_departments(item, payload["details"])
        if item.development_state_id == DevelopmentState.WILLINGNESS:
            item.ensure_agreement_number()
        if "clauses" in payload and payload["clauses"] is not None:
            save_partnership_clauses(item, payload["clauses"], user, allow_progress=True)
        if "teams" in payload and payload["teams"] is not None:
            save_partnership_teams(item, payload["teams"])
        if payload.get("work"):
            from datetime import date as _date
            from django.contrib.auth import get_user_model
            _User = get_user_model()
            wdata = payload["work"]
            assignees = list(_User.objects.filter(pk__in=wdata.get("assignees", []), is_active=True))
            manager = _User.objects.filter(pk=wdata.get("manager"), is_active=True).first()
            if assignees and manager:
                create_partnership_work(
                    user,
                    {
                        "title": wdata["title"],
                        "instructions": wdata.get("instructions", ""),
                        "assignees": assignees,
                        "manager": manager,
                        "due_on": _date.fromisoformat(wdata["due_on"]) if wdata.get("due_on") else None,
                    },
                    item,
                )
        return item


HIGHLIGHT_SESSION_KEY = "partnerships_highlighted_pk"


def _redirect_to_list_with_highlight(request, item, return_to=None):
    request.session[HIGHLIGHT_SESSION_KEY] = item.pk
    if return_to == "willingness" or item.development_state_id == DevelopmentState.WILLINGNESS:
        return redirect("partnerships:willingness_index")
    return redirect("partnerships:capability_index")


@module_view('partnerships')
@login_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def editor(request, pk=None, initial_state=DevelopmentState.CAPABILITY):
    item = get_object_or_404(_query(request.user), pk=pk) if pk else None
    is_will_create = item is None and initial_state == DevelopmentState.WILLINGNESS
    show_edit_clauses = bool(
        item and (item.development_state_id == DevelopmentState.WILLINGNESS or item.agreement_clause_assignments.filter(agreement__isnull=True).exists())
    )
    heading = (
        "تعديل جهة لسجل الشراكات"
        if item
        else ("إضافة جهة لسجل الشراكات المحتملة التي لها الرغبة" if is_will_create else "إضافة جهة لسجل الشراكات المحتملة التي لها القدرة")
    )
    active_nav = "partnerships_willingness" if is_will_create else "partnership_editor"
    context = _base(request, heading, active_nav)
    status, pending = 200, None
    return_to = "willingness" if (request.GET.get("from") == "willingness" or is_will_create or (item and item.development_state_id == DevelopmentState.WILLINGNESS)) else "capability"
    snapshot = _sign({"kind": "editor", "id": pk, "version": item.version if item else None, "nonce": str(uuid.uuid4()), "initial_state": initial_state, "return_to": return_to}, request.user)
    form = PartnershipForm(initial=_initial(item), instance=item, actor=request.user)
    willingness_form = WillingnessTransitionForm() if is_will_create else None
    work_form = PartnershipWorkForm(prefix="work", actor=request.user) if is_will_create else None
    clauses_json = json.dumps(existing_clause_rows(item)) if show_edit_clauses else "[]"
    clauses_error = ""
    details_form = WillingnessDetailsForm(prefix="details", initial=details_initial(item), partnership=item) if (is_will_create or show_edit_clauses) else None
    teams_json = json.dumps(existing_team_rows(item)) if show_edit_clauses else "[]"
    teams_error = ""
    saved_paths = []
    try:
        if request.method == "POST":
            action = request.POST.get("action")
            if is_will_create and action == "create_willingness":
                original = _load(request.POST.get("snapshot"), request.user, "editor")
                if original.get("id") is not None:
                    raise signing.BadSignature
                snapshot = request.POST["snapshot"]
                form = PartnershipForm(request.POST, instance=None, actor=request.user)
                willingness_form = WillingnessTransitionForm(request.POST, request.FILES)
                work_form = PartnershipWorkForm(request.POST, prefix="work", actor=request.user)
                details_form = WillingnessDetailsForm(request.POST, prefix="details")
                clauses_json = request.POST.get("clauses_json", "[]")
                teams_json = request.POST.get("teams_json", "[]")
                parsed_clauses = None
                parsed_teams = None
                try:
                    parsed_clauses = parse_clauses_payload(clauses_json, require_at_least_one=True, allow_progress=False)
                except django_forms.ValidationError as exc:
                    clauses_error = " ".join(exc.messages)
                try:
                    parsed_teams = parse_teams_payload(teams_json)
                except django_forms.ValidationError as exc:
                    teams_error = " ".join(exc.messages)

                if form.is_valid() and willingness_form.is_valid() and work_form.is_valid() and details_form.is_valid() and parsed_clauses is not None and parsed_teams is not None:
                    with regional_transaction(request.user):
                        if not StateColor.objects.filter(pk=DevelopmentState.WILLINGNESS).exists():
                            raise Conflict("حالة رغبة غير موجودة. تأكد من تطبيق ترحيلات حالات التطور.")
                        repeated = Partnership.objects.filter(request_key=original["nonce"]).first()
                        if repeated:
                            require_write(request.user, repeated)
                            return add_login_headers(_redirect_to_list_with_highlight(request, repeated, return_to="willingness"))
                        clean = form.cleaned_data
                        new_item = Partnership(
                            request_key=original["nonce"],
                            created_by=request.user,
                            development_state_id=DevelopmentState.WILLINGNESS,
                        )
                        for field in ["name", "representative", "phone_country", "phone", "email", "entity", "scope", "financial_capacity", "partnership_date", "starts_on", "ends_on"]:
                            setattr(new_item, field, clean[field])
                        new_item.is_active = clean["is_active"] == "1"
                        new_item.save()
                        new_item.administrative_regions.set(clean["administrative_regions"])
                        require_write(request.user, new_item)
                        DevelopmentHistory.objects.create(partnership=new_item, state_id=DevelopmentState.WILLINGNESS, entered_at=new_item.development_state_at)
                        for position, row in enumerate(clean["offerings"]):
                            offering = PartnershipOffering.objects.create(partnership=new_item, sector_id=row["sector"], sponsorship_shape_id=row["shape"], is_active=row["is_active"], position=position)
                            offering.specializations.set(row["specializations"])
                        save_supporting_files(new_item, willingness_form.cleaned_data, request.user, saved_paths)
                        apply_willingness_details(new_item, details_form.cleaned_data, skip_partnership_type_if_empty=True)
                        new_item.save()
                        save_partnership_departments(new_item, details_form.cleaned_data)
                        new_item.ensure_agreement_number()
                        save_partnership_clauses(new_item, parsed_clauses, request.user, allow_progress=False)
                        save_partnership_teams(new_item, parsed_teams)
                        create_partnership_work(request.user, work_form.cleaned_data, new_item)
                    messages.success(request, "تم إنشاء الشراكة في حالة رغبة وحفظ المرفقات وبنود الاتفاقية وإسناد العمل بنجاح.")
                    return add_login_headers(_redirect_to_list_with_highlight(request, new_item, return_to="willingness"))
                else:
                    status = 400
                    context["error"] = "راجع الحقول المطلوبة في البيانات الأساسية والمرفقات وبنود الاتفاقية وإسناد العمل."
            else:
                if int(request.META.get("CONTENT_LENGTH") or 0) > 150000:
                    raise signing.BadSignature
                if action == "preview":
                    original = _load(request.POST.get("snapshot"), request.user, "editor")
                    if original.get("id") != pk or (item and original.get("version") != item.version):
                        raise Conflict("تغيّر السجل منذ فتح النموذج. أعد فتح الصفحة قبل التعديل.")
                    snapshot = request.POST["snapshot"]
                    form = PartnershipForm(request.POST, instance=item, actor=request.user)
                    parsed_clauses = None
                    parsed_teams = None
                    details_valid = True
                    if show_edit_clauses:
                        details_form = WillingnessDetailsForm(request.POST, prefix="details", partnership=item)
                        details_valid = details_form.is_valid()
                        clauses_json = request.POST.get("clauses_json", "[]")
                        teams_json = request.POST.get("teams_json", "[]")
                        try:
                            parsed_clauses = parse_clauses_payload(clauses_json, partnership=item, require_at_least_one=False, allow_progress=True)
                        except django_forms.ValidationError as exc:
                            clauses_error = " ".join(exc.messages)
                        try:
                            parsed_teams = parse_teams_payload(teams_json)
                        except django_forms.ValidationError as exc:
                            teams_error = " ".join(exc.messages)
                    work_valid = True
                    work_payload = None
                    if show_edit_clauses:
                        has_work_input = any(
                            (request.POST.get(k) or "").strip()
                            for k in ("work-title", "work-manager", "work-due_on", "work-instructions")
                        ) or bool(request.POST.getlist("work-assignees"))
                        if has_work_input:
                            work_form = PartnershipWorkForm(request.POST, actor=request.user, prefix="work")
                            work_valid = work_form.is_valid()
                            if work_valid:
                                wc = work_form.cleaned_data
                                work_payload = {
                                    "title": wc["title"],
                                    "instructions": wc.get("instructions") or "",
                                    "assignees": [u.pk for u in wc["assignees"]],
                                    "manager": wc["manager"].pk,
                                    "due_on": wc["due_on"].isoformat() if wc.get("due_on") else "",
                                }
                    if form.is_valid() and details_valid and work_valid and not clauses_error and not teams_error:
                        ensure_allowed(item, "edit", form.cleaned_data["is_active"] == "1")
                        data = _serialized(form.cleaned_data)
                        token_data = {**original, "kind": "save", "data": data, "catalog": _fingerprint(data)}
                        if show_edit_clauses:
                            token_data["clauses"] = parsed_clauses
                            token_data["details"] = serialize_details(details_form.cleaned_data)
                            token_data["teams"] = parsed_teams
                            if work_payload:
                                token_data["work"] = work_payload
                        token = _sign(token_data, request.user)
                        pending = {"title": "تأكيد تعديل الجهة" if item else "تأكيد إضافة الجهة", "name": data["name"], "token": token, "action": "save", "button": "تأكيد الحفظ", "financial_capacity": data["financial_capacity"],
                                   "partnership_date": form.cleaned_data["partnership_date"], "starts_on": form.cleaned_data["starts_on"], "ends_on": form.cleaned_data["ends_on"]}
                    else:
                        status = 400
                elif action == "confirm":
                    payload = _load(request.POST.get("token"), request.user, "save")
                    if payload.get("id") != pk:
                        raise signing.BadSignature
                    form = PartnershipForm(payload["data"], instance=item, actor=request.user)
                    saved = _save(payload, request.user)
                    messages.success(request, "تم حفظ بيانات الجهة بنجاح.")
                    return add_login_headers(_redirect_to_list_with_highlight(request, saved, return_to=payload.get("return_to")))
                else:
                    raise signing.BadSignature
    except DependencyBlocked as exc:
        context.update(blocked_context(exc))
        status = 409
    except signing.BadSignature:
        context["error"], status = "انتهت صلاحية الطلب أو تغيّر محتواه. أعد فتح الصفحة وحاول مجددًا.", 400
    except (Conflict, IntegrityError, ProtectedError) as exc:
        context["error"], status = str(exc) if isinstance(exc, Conflict) else "تعذّر الحفظ؛ اسم الجهة مستخدم أو تغيّرت البيانات المرتبطة. لم يُحفظ أي تغيير.", 409
    except OSError:
        context["error"], status = "تعذّر حفظ المرفقات. لم يُحفظ السجل. حاول مرة أخرى أو تواصل مع مسؤول النظام.", 503
    except Exception:
        delete_private_files(saved_paths)
        raise
    if saved_paths and status >= 400:
        delete_private_files(saved_paths)
    raw_rows = form["offerings"].value() or "[]"
    try:
        drafts = json.loads(raw_rows)
        if not isinstance(drafts, list):
            drafts = []
    except (ValueError, TypeError):
        drafts = []
    existing_works = []
    if show_edit_clauses and item and item.pk:
        from makken_mail.models import WorkAssignment
        from makken_mail.clause_sync import is_work_overdue, riyadh_today
        today_riyadh = riyadh_today()
        existing_works = list(
            WorkAssignment.objects.filter(target_model="partnerships.partnership", target_key=item.pk)
            .select_related("employee", "manager")
            .prefetch_related("assignees")
            .order_by("-pk")
        )
        for _wk in existing_works:
            _wk.is_overdue = is_work_overdue(_wk, today_riyadh)
        if work_form is None:
            work_form = PartnershipWorkForm(actor=request.user, prefix="work", optional=True)
    back_url = reverse("partnerships:willingness_index") if return_to == "willingness" else reverse("partnerships:capability_index")
    context.update(
        existing_works=existing_works,
        item=item,
        form=form,
        snapshot=snapshot,
        pending=pending,
        catalog=_catalog(item),
        drafts=drafts,
        history=_history(item),
        back_url=back_url,
        is_will_create=is_will_create,
        show_edit_clauses=show_edit_clauses,
        willingness_form=willingness_form,
        work_form=work_form,
        clauses_json=clauses_json,
        clauses_error=clauses_error,
        details_form=details_form,
        teams_json=teams_json,
        teams_error=teams_error,
        clause_catalog_data=clause_catalog(item),
    )
    return add_login_headers(render(request, "partnerships/editor.html", context, status=status))


@module_view('partnerships')
@login_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def editor_willingness(request):
    return editor(request, pk=None, initial_state=DevelopmentState.WILLINGNESS)


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
        condition = (Q(name__icontains=word) | Q(agreement_number__icontains=word) | Q(representative__icontains=word) | Q(phone__icontains=word) | Q(email__icontains=word) | Q(entity__name__icontains=word) | Q(offerings__sector__name__icontains=word) | Q(offerings__specializations__name__icontains=word) | Q(offerings__sponsorship_shape__name__icontains=word)) | financial_search_clause(word)
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


def _render_index(request, fixed_state=None, read_only=False):
    if read_only:
        heading, active_nav = "جميع الشراكات", "partnerships_all"
        add_url, reset_url = "", reverse("partnerships:all_index")
    elif fixed_state == DevelopmentState.CAPABILITY:
        heading, active_nav = "إدارة سجل شراكات القدرة", "partnerships_capability"
        add_url, reset_url = reverse("partnerships:create"), reverse("partnerships:capability_index")
    elif fixed_state == DevelopmentState.WILLINGNESS:
        heading, active_nav = "إدارة سجل شراكات الرغبة", "partnerships_willingness"
        add_url, reset_url = reverse("partnerships:create_willingness"), reverse("partnerships:willingness_index")
    else:
        heading, active_nav = "إدارة سجل الشراكات", "partnerships"
        add_url, reset_url = reverse("partnerships:create"), reverse("partnerships:index")
    context = _base(request, heading, active_nav)
    status, pending = 200, None
    saved_paths = []
    willingness_form = WillingnessTransitionForm()
    work_form = PartnershipWorkForm(prefix="work", actor=request.user)
    details_form = WillingnessDetailsForm(prefix="details")
    clauses_json = "[]"
    clauses_error = ""
    teams_json = "[]"
    teams_error = ""
    try:
        if request.method == "POST":
            action = request.POST.get("action")
            if action not in {"preview", "confirm"}:
                raise signing.BadSignature
            data = _load(request.POST.get("token"), request.user, "row" if action == "preview" else "row-confirm")
            if data.get("operation") not in {"delete", "toggle", "advance"}:
                raise signing.BadSignature
            with regional_transaction(request.user) as region_policy:
                item = Partnership.objects.select_for_update().filter(pk=data.get("id")).first()
                if not item or item.version != data.get("version"):
                    raise Conflict("تغيّر هذا السجل أو حُذف، أو تم تنفيذ الطلب مسبقًا. حدّث القائمة وحاول مجددًا.")
                require_write(request.user, item, policy=region_policy)
                ensure_allowed(item, data["operation"], not item.is_active if data["operation"] == "toggle" else None)
                if data["operation"] == "advance":
                    if item.development_state_id != DevelopmentState.CAPABILITY:
                        raise Conflict("يمكن الانتقال إلى رغبة فقط عندما تكون الحالة الحالية قدرة. لم يتغير السجل.")
                    if not StateColor.objects.filter(pk=DevelopmentState.WILLINGNESS).exists():
                        raise Conflict("حالة رغبة غير موجودة. تأكد من تطبيق ترحيلات حالات التطور.")
                if action == "preview":
                    operation = data["operation"]
                    pending = {"title": "تأكيد حذف الجهة" if operation == "delete" else "تأكيد تغيير حالة السجل", "name": item.name, "action": operation, "button": "نعم، حذف الجهة" if operation == "delete" else "تأكيد التغيير", "token": _sign({**data, "kind": "row-confirm"}, request.user)}
                    if operation == "advance":
                        pending.update(title="التحويل من قدرة إلى رغبة", button="حفظ والتحويل إلى رغبة")
                else:
                    if data["operation"] == "advance":
                        willingness_form = WillingnessTransitionForm(request.POST, request.FILES, partnership=item)
                        work_form = PartnershipWorkForm(request.POST, prefix="work", actor=request.user)
                        details_form = WillingnessDetailsForm(request.POST, prefix="details")
                        clauses_json = request.POST.get("clauses_json", "[]")
                        teams_json = request.POST.get("teams_json", "[]")
                        parsed_clauses = None
                        parsed_teams = None
                        try:
                            parsed_clauses = parse_clauses_payload(clauses_json, partnership=item, require_at_least_one=True, allow_progress=False)
                        except django_forms.ValidationError as exc:
                            clauses_error = " ".join(exc.messages)
                        try:
                            parsed_teams = parse_teams_payload(teams_json)
                        except django_forms.ValidationError as exc:
                            teams_error = " ".join(exc.messages)

                        if not (willingness_form.is_valid() and work_form.is_valid() and details_form.is_valid() and parsed_clauses is not None and parsed_teams is not None):
                            pending = {"title": "التحويل من قدرة إلى رغبة", "name": item.name, "action": "advance", "button": "حفظ والتحويل إلى رغبة", "token": request.POST.get("token")}
                            raise InvalidWillingnessForm

                        # No state/date changes until documents, clauses, details, and work assignment are all validated and stored.
                        save_supporting_files(item, willingness_form.cleaned_data, request.user, saved_paths)
                        entered_at = timezone.now()
                        if not item.development_history.filter(state_id=DevelopmentState.CAPABILITY).exists():
                            DevelopmentHistory.objects.create(partnership=item, state_id=DevelopmentState.CAPABILITY, entered_at=item.development_state_at)
                        DevelopmentHistory.objects.create(partnership=item, state_id=DevelopmentState.WILLINGNESS, entered_at=entered_at)
                        item.development_state_id = DevelopmentState.WILLINGNESS
                        item.development_state_at = entered_at
                        item.version += 1
                        apply_willingness_details(item, details_form.cleaned_data, skip_partnership_type_if_empty=True)
                        item.save()
                        save_partnership_departments(item, details_form.cleaned_data)
                        item.ensure_agreement_number()
                        save_partnership_clauses(item, parsed_clauses, request.user, allow_progress=False)
                        save_partnership_teams(item, parsed_teams)
                        create_partnership_work(request.user, work_form.cleaned_data, item)
                        message = "تم حفظ المرفقات وبنود الاتفاقية وإسناد العمل وتحويل الجهة إلى رغبة بنجاح."
                    elif data["operation"] == "delete":
                        item.delete()
                        message = "تم حذف الجهة وبيانات شراكتها بنجاح."
                    else:
                        item.is_active = not item.is_active
                        item.version += 1
                        item.save(update_fields=["is_active", "version", "updated_at"])
                        message = "تم تحديث حالة السجل بنجاح."
                    messages.success(request, message)
                    if data["operation"] == "advance":
                        destination = _redirect_to_list_with_highlight(request, item, return_to="willingness")
                        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                            return add_login_headers(JsonResponse({"redirect": destination.url}))
                        return add_login_headers(destination)
                    destination = financial_redirect(request)
                    return add_login_headers(destination)
    except DependencyBlocked as exc:
        context.update(blocked_context(exc))
        status = 409
    except InvalidWillingnessForm:
        context["error"], status = "راجع نوع الاتفاق والمرفقات وبنود الاتفاقية وإسناد العمل قبل تأكيد التحويل.", 400
    except signing.BadSignature:
        context["error"], status = "انتهت صلاحية الطلب أو تغيّر محتواه. أعد فتح الصفحة وحاول مجددًا.", 400
    except (Conflict, IntegrityError, ProtectedError) as exc:
        context["error"], status = str(exc) if isinstance(exc, Conflict) else "تعذّر تنفيذ الطلب لوجود بيانات مرتبطة.", 409
    except OSError:
        context["error"], status = "تعذّر حفظ المرفقات. لم تتغير حالة الجهة. حاول مرة أخرى أو تواصل مع مسؤول النظام.", 503
    except Exception:
        delete_private_files(saved_paths)
        raise
    if saved_paths and status >= 400:
        delete_private_files(saved_paths)
    if status >= 400 and request.headers.get("X-Requested-With") == "XMLHttpRequest":
        combined_errors = dict(willingness_form.errors.get_json_data())
        if clauses_error:
            combined_errors["clauses"] = [{"message": clauses_error, "code": "invalid"}]
        if teams_error:
            combined_errors["teams"] = [{"message": teams_error, "code": "invalid"}]
        for field_name, items in work_form.errors.get_json_data().items():
            combined_errors[f"work-{field_name}"] = items
        for field_name, items in details_form.errors.get_json_data().items():
            combined_errors[f"details-{field_name}"] = items
        return add_login_headers(JsonResponse({"error": context.get("error", "تعذّر الحفظ."), "errors": combined_errors}, status=status))
    context["willingness_form"] = willingness_form
    context["work_form"] = work_form
    context["details_form"] = details_form
    context["clauses_json"] = clauses_json
    context["clauses_error"] = clauses_error
    context["teams_json"] = teams_json
    context["teams_error"] = teams_error
    context["clause_catalog_data"] = clause_catalog()
    q = request.GET.get("q", "").strip()[:200]
    active = request.GET.get("status", "")
    query = _search(_query(request.user), q)
    if active in {"1", "0"}:
        query = query.filter(is_active=active == "1")
    if fixed_state == DevelopmentState.CAPABILITY:
        query = query.filter(development_state_id=DevelopmentState.CAPABILITY)
        development = DevelopmentFilter(request, query, exact=True, allowed_states=(DevelopmentState.CAPABILITY,))
        context.update(development.context)
        if not development.valid:
            status = 400
        query = development.queryset
    elif fixed_state == DevelopmentState.WILLINGNESS:
        query = query.filter(development_state_id__in=[DevelopmentState.WILLINGNESS, DevelopmentState.CAPABILITY])
        development = DevelopmentFilter(
            request,
            query,
            exact=True,
            allowed_states=(DevelopmentState.CAPABILITY, DevelopmentState.WILLINGNESS),
        )
        context.update(development.context)
        if not development.valid:
            status = 400
        query = development.queryset
    else:
        development = DevelopmentFilter(request, query, exact=read_only)
        context.update(development.context)
        if not development.valid:
            status = 400
        query = development.queryset
    # MAKKEN FINANCIAL RANGE
    financial = FinancialRange(request, query)
    context.update(financial.context)
    if not financial.valid:
        status = 400
    query = financial.queryset
    highlighted_pk = request.session.pop(HIGHLIGHT_SESSION_KEY, None) if request.method == "GET" else None
    page_number = request.GET.get("page")
    if highlighted_pk and not page_number:
        ordered_pks = list(query.values_list("pk", flat=True))
        if highlighted_pk in ordered_pks:
            page_number = (ordered_pks.index(highlighted_pk) // 15) + 1
    page = Paginator(query, 15).get_page(page_number)
    rows = []
    for item in page:
        token = {"kind": "row", "id": item.pk, "version": item.version}
        rows.append({"item": item, "toggle": _sign({**token, "operation": "toggle"}, request.user), "delete": _sign({**token, "operation": "delete"}, request.user), "advance": _sign({**token, "operation": "advance"}, request.user) if item.development_state_id == DevelopmentState.CAPABILITY else None})
    detail = None
    if request.GET.get("detail"):
        value = request.GET["detail"]
        if not value.isascii() or not value.isdecimal() or len(value) > 18:
            raise Http404
        detail = get_object_or_404(_query(request.user), pk=int(value))
    params = {"q": q, "status": active, "page": page.number}
    # MAKKEN FINANCIAL QUERY PARAMS
    params.update(financial.params)
    if development is not None:
        params.update(development.params)
    context["financial_pagination_query"] = urlencode({key: value for key, value in params.items() if key != "page"})
    result_query = urlencode(params)
    if detail:
        from agreement_clauses.workflow import partnership_panel
        context["clause_panel"] = partnership_panel(detail)
    context.update(rows=rows, page_obj=page, highlighted_pk=highlighted_pk, q=q, selected_status=active, pending=pending, detail=detail, history=_history(detail), result_query=result_query, list_url=reset_url + "?" + result_query, add_url=add_url, read_only=read_only, reset_url=reset_url, hide_development_filter=False, show_agreement_number=(fixed_state == DevelopmentState.WILLINGNESS))
    return add_login_headers(render(request, "partnerships/index.html", context, status=status))


@module_view('partnerships')
@login_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def index(request, fixed_state=None, read_only=False):
    return _render_index(request, fixed_state=fixed_state, read_only=read_only)


@module_view('partnerships')
@login_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def capability_index(request):
    return _render_index(request, fixed_state=DevelopmentState.CAPABILITY)


@module_view('partnerships')
@login_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def willingness_index(request):
    return _render_index(request, fixed_state=DevelopmentState.WILLINGNESS)


@module_view('partnerships_all')
@login_required(login_url="accounts:login")
@require_http_methods(["GET", "HEAD"])
def all_index(request):
    return _render_index(request, fixed_state=None, read_only=True)


@module_view('partnerships')
@login_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def clauses_progress(request, pk):
    from django.http import FileResponse
    from access_control.activity_capture import emit, regions_for
    from access_control.activity_data import audit_timezone
    from agreement_clauses.models import ClauseAssignment, ClauseEvidence, mean_progress
    from .willingness import safe_filename, validate_attachment
    from .attachment_storage import willingness_storage

    item = get_object_or_404(_query(request.user), pk=pk)
    if item.development_state_id != DevelopmentState.WILLINGNESS:
        return add_login_headers(
            JsonResponse({"error": "بطاقة المتابعة ونسب إنجاز البنود متاحة لشراكات الرغبة فقط."}, status=400)
        )

    def _serialize_payload(partnership):
        partnership.refresh_from_db()
        rows = list(
            ClauseAssignment.objects.select_related("clause")
            .prefetch_related("evidences")
            .filter(partnership=partnership, agreement__isnull=True)
            .order_by("id")
        )
        overall = mean_progress(sum(r.progress for r in rows), len(rows))
        overall_str = "—" if overall is None else (f"{int(overall)}%" if overall == int(overall) else f"{overall:.2f}%")
        tz = audit_timezone()
        updated_at_display = (
            timezone.localtime(partnership.followup_updated_at, tz).strftime("%d/%m/%Y %H:%M")
            if partnership.followup_updated_at
            else ""
        )
        updated_by_name = ""
        if partnership.followup_updated_by:
            updated_by_name = partnership.followup_updated_by.get_full_name() or partnership.followup_updated_by.get_username()
        return {
            "partnership_id": partnership.pk,
            "partnership_name": partnership.name,
            "agreement_number": partnership.agreement_number or "—",
            "overall_progress": float(overall) if overall is not None else None,
            "overall_display": overall_str,
            "followup_updated_at_display": updated_at_display,
            "followup_updated_by_name": updated_by_name,
            "teams": existing_team_rows(partnership),
            "clauses": [
                {
                    "id": r.pk,
                    "clause_id": r.clause_id,
                    "name": r.clause.name,
                    "responsibility": r.responsibility,
                    "responsibility_label": r.get_responsibility_display(),
                    "progress": r.progress,
                    "notes": r.notes or "",
                    "evidences": [
                        {
                            "id": ev.pk,
                            "name": ev.original_name,
                            "size": ev.size,
                            "download_url": reverse(
                                "partnerships:clause_evidence_download",
                                kwargs={"pk": partnership.pk, "evidence_id": ev.pk},
                            ),
                            "uploaded_at": timezone.localtime(ev.uploaded_at, tz).strftime("%d/%m/%Y %H:%M"),
                        }
                        for ev in r.evidences.all()
                    ],
                }
                for r in rows
            ],
        }

    if request.method == "GET":
        return add_login_headers(JsonResponse(_serialize_payload(item)))

    content_type = (request.content_type or "").lower()
    teams_submitted = False
    raw_teams_json = None
    if content_type.startswith("application/json"):
        try:
            body = json.loads((request.body or b"{}").decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return add_login_headers(JsonResponse({"error": "بيانات الطلب غير صالحة."}, status=400))
        raw_items = body.get("items")
        if "teams" in body:
            teams_submitted = True
            raw_teams_json = json.dumps(body.get("teams") or [])
    else:
        try:
            raw_items = json.loads(request.POST.get("items_json", "[]"))
        except (ValueError, TypeError):
            return add_login_headers(JsonResponse({"error": "قائمة البنود غير صالحة."}, status=400))
        if "teams_json" in request.POST:
            teams_submitted = True
            raw_teams_json = request.POST.get("teams_json", "[]")

    if not isinstance(raw_items, list):
        return add_login_headers(JsonResponse({"error": "قائمة البنود غير صالحة."}, status=400))

    updates = {}
    for entry in raw_items:
        if not isinstance(entry, dict):
            return add_login_headers(JsonResponse({"error": "تنسيق البند غير صالح."}, status=400))
        try:
            assignment_id = int(entry.get("id"))
            progress_val = int(entry.get("progress"))
        except (TypeError, ValueError):
            return add_login_headers(JsonResponse({"error": "أدخل نسبة إنجاز صحيحة بين 0 و100 لكل بند."}, status=400))
        if progress_val < 0 or progress_val > 100:
            return add_login_headers(JsonResponse({"error": "يجب أن تكون نسبة الإنجاز بين 0% و100%."}, status=400))
        notes_val = str(entry.get("notes") or "").strip()[:2000]
        updates[assignment_id] = {"progress": progress_val, "notes": notes_val, "has_notes": "notes" in entry}

    parsed_teams = None
    if teams_submitted:
        try:
            parsed_teams = parse_teams_payload(raw_teams_json)
        except django_forms.ValidationError as exc:
            return add_login_headers(JsonResponse({"error": " ".join(exc.messages)}, status=400))

    # Validate any uploaded per-clause evidence files (evidence_<assignment_id>)
    validated_files = {}
    for field_key in request.FILES:
        if not field_key.startswith("evidence_"):
            continue
        raw_aid = field_key[len("evidence_"):]
        if not raw_aid.isdigit():
            return add_login_headers(JsonResponse({"error": "معرّف البند للمرفق غير صالح."}, status=400))
        aid = int(raw_aid)
        files = request.FILES.getlist(field_key)
        for upload in files:
            try:
                validated_files.setdefault(aid, []).append(validate_attachment(upload))
            except django_forms.ValidationError as exc:
                return add_login_headers(JsonResponse({"error": f"{safe_filename(getattr(upload, 'name', 'مرفق'))}: {' '.join(exc.messages)}"}, status=400))

    saved_paths = []
    try:
        with regional_transaction(request.user) as region_policy:
            locked_item = Partnership.objects.select_for_update().filter(pk=item.pk).first()
            if not locked_item:
                return add_login_headers(JsonResponse({"error": "الشراكة غير موجودة."}, status=404))
            require_write(request.user, locked_item, policy=region_policy)
            assignments = {
                r.pk: r
                for r in ClauseAssignment.objects.select_for_update().filter(
                    partnership=locked_item, agreement__isnull=True
                )
            }
            changed = []
            for aid, vals in updates.items():
                row = assignments.get(aid)
                if row is None:
                    return add_login_headers(JsonResponse({"error": "أحد البنود المحددة غير مرتبط بهذه الشراكة."}, status=400))
                new_prog = vals["progress"]
                new_notes = vals["notes"] if vals["has_notes"] else row.notes
                if row.progress != new_prog or row.notes != new_notes:
                    old_prog = row.progress
                    row.progress = new_prog
                    row.notes = new_notes
                    row.version += 1
                    row.updated_by = request.user
                    row.save(update_fields=["progress", "notes", "version", "updated_by", "updated_at"])
                    changed.append({"id": aid, "before": old_prog, "after": new_prog})

            storage = willingness_storage()
            for aid, uploads in validated_files.items():
                row = assignments.get(aid)
                if row is None:
                    return add_login_headers(JsonResponse({"error": "أحد مرفقات الشواهد يشير إلى بند غير مرتبط بهذه الشراكة."}, status=400))
                for upload in uploads:
                    name = "clause_evidence/" + uuid.uuid4().hex + Path(upload.name).suffix.lower()
                    saved_paths.append(name)
                    actual = storage.save(name, upload)
                    if actual != name:
                        saved_paths.append(actual)
                    ClauseEvidence.objects.create(
                        assignment=row,
                        file=actual,
                        original_name=safe_filename(upload.name),
                        size=upload.size,
                        content_type=upload.verified_content_type,
                        uploaded_by=request.user,
                    )

            if parsed_teams is not None:
                save_partnership_teams(locked_item, parsed_teams)

            locked_item.followup_updated_at = timezone.now()
            locked_item.followup_updated_by = request.user
            locked_item.save(update_fields=["followup_updated_at", "followup_updated_by", "updated_at"])

            emit(
                actor=request.user,
                module="partnerships",
                action="update",
                description="تحديث بطاقة المتابعة ونسب إنجاز بنود الشراكة",
                target_model="partnerships.partnership",
                target_key=str(locked_item.pk),
                target_label=locked_item.name,
                before={"clauses": [{"id": c["id"], "progress": c["before"]} for c in changed]},
                after={"clauses": [{"id": c["id"], "progress": c["after"]} for c in changed]},
                regions=regions_for(locked_item),
            )
    except Exception:
        delete_private_files(saved_paths)
        raise

    payload = _serialize_payload(item)
    payload["message"] = "تم حفظ بطاقة المتابعة بنجاح. يمكنك متابعة التعديل أو إغلاق النافذة."
    return add_login_headers(JsonResponse(payload))


@module_view('partnerships')
@login_required(login_url="accounts:login")
@require_http_methods(["GET"])
def download_clause_evidence(request, pk, evidence_id):
    from django.http import FileResponse
    from agreement_clauses.models import ClauseEvidence
    from .attachment_storage import willingness_storage

    partnership = get_object_or_404(_query(request.user), pk=pk)
    evidence = get_object_or_404(
        ClauseEvidence.objects.select_related("assignment"),
        pk=evidence_id,
        assignment__partnership=partnership,
        assignment__agreement__isnull=True,
    )
    try:
        source = willingness_storage().open(evidence.file, "rb")
    except OSError as exc:
        raise Http404("الملف غير متاح.") from exc
    response = FileResponse(source, as_attachment=True, filename=evidence.original_name, content_type=evidence.content_type)
    response["X-Content-Type-Options"] = "nosniff"
    return add_login_headers(response)


@module_view('partnerships')
@login_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def work_assignment_edit(request, pk, work_pk):
    from datetime import date
    from django.contrib.auth import get_user_model
    from django.db.models import F
    from access_control.regions import RegionalPolicy
    from makken_mail.clause_sync import calculate_partnership_clause_progress, derive_status_and_progress, is_work_overdue
    from makken_mail.models import WorkAssignment, WorkHistory, WorkStatus

    User = get_user_model()
    item = get_object_or_404(_query(request.user), pk=pk)
    wk = get_object_or_404(
        WorkAssignment.objects.select_related("employee", "manager").prefetch_related("assignees"),
        pk=work_pk,
        target_model="partnerships.partnership",
        target_key=item.pk,
    )

    users_qs = User.objects.filter(is_active=True).order_by("first_name", "last_name", "username")
    if not request.user.is_superuser:
        reg = RegionalPolicy(request.user)
        if not reg.unrestricted:
            users_qs = users_qs.filter(
                Q(is_superuser=True)
                | Q(access_profile__region_scope="all")
                | Q(access_profile__allowed_regions__in=reg.ids)
            ).distinct()
    allowed_users = list(users_qs)
    allowed_user_map = {u.pk: u for u in allowed_users}

    def _display_name(u):
        return (u.get_full_name() or "").strip() or u.username

    def _serialize(assignment):
        assignees = list(assignment.assignees.all()) or ([assignment.employee] if assignment.employee_id else [])
        return {
            "id": assignment.pk,
            "title": assignment.title,
            "instructions": assignment.instructions or "",
            "assignee_ids": [u.pk for u in assignees],
            "assignees_names": [_display_name(u) for u in assignees],
            "manager_id": assignment.manager_id,
            "manager_name": _display_name(assignment.manager),
            "status": assignment.status,
            "status_display": assignment.get_status_display(),
            "progress": assignment.progress,
            "is_overdue": is_work_overdue(assignment),
            "auto_synced": True,
            "due_on": assignment.due_on.isoformat() if assignment.due_on else "",
            "status_choices": [{"value": v, "label": lbl} for v, lbl in WorkStatus.choices],
            "users": [{"id": u.pk, "name": _display_name(u)} for u in allowed_users],
        }

    if request.method == "GET":
        return add_login_headers(JsonResponse({"ok": True, "work": _serialize(wk)}))

    try:
        payload = json.loads(request.body.decode("utf-8")) if request.content_type and "json" in request.content_type else request.POST
    except (ValueError, UnicodeDecodeError):
        return add_login_headers(JsonResponse({"error": "بيانات الطلب غير صالحة."}, status=400))

    title = (payload.get("title") or "").strip()
    if not title:
        return add_login_headers(JsonResponse({"error": "أدخل عنوان المهمة."}, status=400))
    if len(title) > 160:
        return add_login_headers(JsonResponse({"error": "عنوان المهمة أطول من الحد المسموح (160 حرفًا)."}, status=400))

    raw_assignees = payload.get("assignee_ids") if isinstance(payload, dict) else request.POST.getlist("assignee_ids")
    if not isinstance(raw_assignees, list) or not raw_assignees:
        return add_login_headers(JsonResponse({"error": "اختر موظفًا واحدًا على الأقل لإسناد المهمة."}, status=400))
    try:
        assignee_ids = list(dict.fromkeys(int(x) for x in raw_assignees))
        manager_id = int(payload.get("manager_id") or 0)
    except (TypeError, ValueError):
        return add_login_headers(JsonResponse({"error": "اختر موظفين ومشرفًا صالحين."}, status=400))

    if any(uid not in allowed_user_map for uid in assignee_ids):
        return add_login_headers(JsonResponse({"error": "أحد الموظفين المختارين غير متاح ضمن نطاقك."}, status=400))
    if manager_id not in allowed_user_map:
        return add_login_headers(JsonResponse({"error": "اختر المشرف / المدير من القائمة."}, status=400))
    if manager_id in assignee_ids:
        return add_login_headers(JsonResponse({"error": "لا يمكن أن يكون المشرف / المدير ضمن الموظفين المسند إليهم."}, status=400))

    requested_status = (payload.get("status") or "").strip()
    if requested_status == WorkStatus.CANCELLED:
        status_val = WorkStatus.CANCELLED
        progress_val = min(wk.progress, 99)
    else:
        clause_pct = calculate_partnership_clause_progress(item.pk)
        status_val, progress_val = derive_status_and_progress(clause_pct, WorkStatus.NEW)

    due_raw = (payload.get("due_on") or "").strip()
    due_val = None
    if due_raw:
        try:
            due_val = date.fromisoformat(due_raw)
        except ValueError:
            return add_login_headers(JsonResponse({"error": "صيغة تاريخ الاستحقاق غير صحيحة."}, status=400))

    instructions = (payload.get("instructions") or "").strip()[:3000]

    with regional_transaction(request.user) as region_policy:
        require_write(request.user, item, policy=region_policy)
        wk.title = title
        wk.instructions = instructions
        wk.employee_id = assignee_ids[0]
        wk.manager_id = manager_id
        wk.status = status_val
        wk.progress = progress_val
        wk.due_on = due_val
        wk.revision = F("revision") + 1
        wk.save()
        wk.assignees.set(assignee_ids)
        wk.refresh_from_db()
        WorkHistory.objects.create(
            assignment=wk,
            actor=request.user,
            action="updated",
            snapshot={
                "title": wk.title,
                "status": wk.status,
                "progress": wk.progress,
                "manager": wk.manager_id,
                "assignees": assignee_ids,
                "due_on": wk.due_on.isoformat() if wk.due_on else "",
            },
            note="تحديث المهمة من صفحة تعديل الشراكة",
        )

    return add_login_headers(JsonResponse({"ok": True, "work": _serialize(wk)}))
