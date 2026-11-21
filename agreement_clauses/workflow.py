from django.contrib import messages
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from access_control.activity_capture import emit, regions_for
from access_control.enforcement import module_view
from access_control.policy import require
from access_control.regions import regional_transaction, require_write, scoped
from accounts.security import add_login_headers
from partnerships.models import Partnership
from .forms import AgreementTitleForm, AssignForm, ProgressForm
from .models import Agreement, AgreementClause, AgreementFollowupState, ClauseAssignment, mean_progress

SALT = "makken.agreement-clauses.workflow.v1"
OPERATIONS = {"create_agreement": "create", "rename_agreement": "edit", "add_clauses": "edit",
              "update_clause": "edit", "remove_clause": "delete"}


class WorkflowConflict(Exception):
    pass


class InvalidInput(Exception):
    def __init__(self, form):
        self.form = form


def assignments(partnership, agreement=None):
    return (ClauseAssignment.objects.filter(agreement=agreement) if agreement else
            ClauseAssignment.objects.filter(partnership=partnership))


def summarize(query):
    values = query.aggregate(total=Sum('progress'), count=Count('pk'))
    return mean_progress(values['total'], values['count'])


def partnership_progress(partnership):
    return summarize(ClauseAssignment.objects.filter(Q(partnership=partnership) | Q(agreement__partnership=partnership)))


def partnership_panel(partnership):
    return {"partnership": partnership, "overall": partnership_progress(partnership),
            "assignment_count": assignments(partnership).count(), "agreement_count": partnership.agreements.count()}


def token(actor, partnership, agreement, **state):
    return signing.dumps({"user": actor.pk, "partnership": partnership.pk,
                          "agreement": agreement.pk if agreement else None, **state}, salt=SALT)


def validate_token(raw, actor, partnership, agreement):
    if not raw or len(raw) > 4096:
        raise signing.BadSignature
    data = signing.loads(raw, salt=SALT, max_age=20 * 60)
    if data.get("user") != actor.pk or data.get("partnership") != partnership.pk or data.get("agreement") != (agreement.pk if agreement else None):
        raise signing.BadSignature
    return data


def snapshot(row):
    return {"clause": row.clause.name, "responsibility": row.get_responsibility_display(), "progress": row.progress,
            **({"agreement_number": row.agreement.number} if row.agreement_id else {})}


def audit(actor, partnership, text, before=None, after=None, progress=False):
    regions = regions_for(partnership)
    emit(actor=actor, module="partnerships", action="update", description=text,
         target_model="partnerships.partnership", target_key=str(partnership.pk),
         target_label=partnership.name, before=before or {}, after=after or {},
         regions=regions, scope="regional" if regions else "unknown", live=progress)


def touch_followup(agreement, actor):
    if agreement:
        AgreementFollowupState.objects.update_or_create(agreement=agreement, defaults={'updated_by': actor})


def agree_title(partnership, agreement, title):
    existing = Agreement.objects.filter(partnership=partnership, title__iexact=title)
    if agreement:
        existing = existing.exclude(pk=agreement.pk)
    if existing.exists():
        raise WorkflowConflict("توجد اتفاقية بهذا العنوان لهذه الشراكة.")


def change(actor, partnership_id, agreement_id, post):
    operation = post.get("operation")
    if operation not in OPERATIONS:
        raise signing.BadSignature
    with regional_transaction(actor) as policy:
        actor = policy.user
        require(actor, 'partnerships', 'view', OPERATIONS[operation])
        partnership = get_object_or_404(scoped(Partnership.objects.select_for_update(), policy=policy), pk=partnership_id)
        require_write(actor, partnership, policy=policy)
        agreement = get_object_or_404(Agreement.objects.select_for_update(), pk=agreement_id, partnership=partnership) if agreement_id else None
        state = validate_token(post.get("snapshot"), actor, partnership, agreement)
        if not partnership.is_active:
            raise WorkflowConflict("يجب تفعيل الشراكة أولًا لتعديل الاتفاقيات أو البنود.")

        if operation == "create_agreement":
            raise PermissionDenied("تم إلغاء إنشاء الاتفاقيات المنفصلة؛ تُدار البنود مباشرة عبر الشراكة.")
        if operation == "rename_agreement":
            if (operation == "rename_agreement") != bool(agreement) or state.get("kind") != "title":
                raise signing.BadSignature
            if agreement and state.get("title") != agreement.title:
                raise WorkflowConflict("تغيّر عنوان الاتفاقية. حدّث الصفحة قبل الحفظ.")
            form = AgreementTitleForm(post, prefix="main")
            if not form.is_valid():
                raise InvalidInput(form)
            title = form.cleaned_data["title"]
            if agreement and title == agreement.title:
                return agreement, "لا توجد تغييرات."
            agree_title(partnership, agreement, title)
            if agreement:
                old = agreement.title
                agreement.title = title
                agreement.save(update_fields=["title"])
                touch_followup(agreement, actor)
                audit(actor, partnership, "تعديل عنوان اتفاقية", {"agreement_title": old}, {"agreement_title": title, "agreement_number": agreement.number})
            else:
                agreement = Agreement.objects.create(partnership=partnership, title=title, created_by=actor)
                audit(actor, partnership, "إضافة اتفاقية", after={"agreement_title": title, "agreement_number": agreement.number})
            return agreement, "تم حفظ الاتفاقية."

        children = assignments(partnership, agreement)
        if operation == "add_clauses":
            if state.get("kind") != "add":
                raise signing.BadSignature
            # The parent serializes assignments. Catalogue transitions lock
            # the same selected rows before checking incoming references.
            bound = AssignForm(post, assigned=list(children.values_list('clause_id', flat=True)))
            if not bound.is_valid():
                raise InvalidInput(bound)
            ids = [row.pk for row in bound.cleaned_data["clauses"]]
            selected = list(AgreementClause.objects.select_for_update().filter(pk__in=ids, is_active=True).order_by("pk"))
            if len(selected) != len(ids):
                raise WorkflowConflict("تغيّرت حالة أحد البنود المحددة. حدّث الصفحة واختَر البنود النشطة.")
            if children.count() + len(selected) > 100:
                raise WorkflowConflict("الحد الأقصى 100 بند لكل اتفاقية أو مجموعة بنود مباشرة.")
            responsibility = bound.cleaned_data["responsibility"]
            children.bulk_create([ClauseAssignment(clause=clause, agreement=agreement,
                partnership=None if agreement else partnership, responsibility=responsibility, updated_by=actor) for clause in selected])
            touch_followup(agreement, actor)
            audit(actor, partnership, "إسناد بنود الاتفاقية", after={"agreement_clauses": [clause.name for clause in selected]})
            return agreement, "تم إسناد البنود."

        if state.get("kind") != "row" or type(state.get("row")) is not int:
            raise signing.BadSignature
        row = children.select_for_update().filter(pk=state["row"]).first()
        if row is None or row.version != state.get("version"):
            raise WorkflowConflict("تغيّر هذا البند منذ فتح الصفحة. حدّثها قبل إعادة المحاولة.")
        before = snapshot(row)
        if operation == "remove_clause":
            row.delete()
            touch_followup(agreement, actor)
            audit(actor, partnership, "إزالة إسناد بند", before=before)
            return agreement, "تمت إزالة ارتباط البند. البند الأصلي ما زال موجودًا في الدليل."

        form = ProgressForm(post, prefix=f"row-{row.pk}")
        if not form.is_valid():
            raise InvalidInput(form)
        if row.responsibility == form.cleaned_data["responsibility"] and row.progress == form.cleaned_data["progress"]:
            return agreement, "لا توجد تغييرات."
        row.responsibility = form.cleaned_data["responsibility"]
        row.progress = form.cleaned_data["progress"]
        row.version += 1
        row.updated_by = actor
        row.save()
        touch_followup(agreement, actor)
        audit(actor, partnership, "تحديث إنجاز بند الاتفاقية", before, snapshot(row),
              progress=before["progress"] != row.progress)
        return agreement, "تم حفظ مسؤولية البند ونسبة إنجازه."


@module_view("partnerships")
@require_http_methods(["GET", "POST"])
def workflow(request, pk, agreement_id=None):
    partnership = get_object_or_404(scoped(Partnership.objects.all(), request.user), pk=pk)
    agreement = get_object_or_404(partnership.agreements, pk=agreement_id) if agreement_id else None
    from .followup import FOLLOWUP_OPERATIONS, InvalidFollowup, change_followup, followup_context

    status, error, invalid, followup_errors = 200, "", None, {}
    if request.method == "POST":
        operation = request.POST.get("operation")
        try:
            if operation in FOLLOWUP_OPERATIONS:
                agreement, message = change_followup(request, pk, agreement_id)
                anchor = "#agreement-teams" if operation == "save_followup_teams" else "#agreement-updates"
                destination = reverse("partnerships:agreement", args=[pk, agreement.pk]) + anchor
            else:
                agreement, message = change(request.user, pk, agreement_id, request.POST)
                destination = (reverse("partnerships:agreement", args=[pk, agreement.pk]) if agreement else
                               reverse("partnerships:clauses", args=[pk]))
            messages.success(request, message)
            return add_login_headers(redirect(destination))
        except InvalidFollowup as exc:
            followup_errors, status = exc.context, 400
        except OSError:
            error, status = "تعذّر حفظ المرفقات. حاول مجددًا أو تواصل مع الدعم.", 503
        except InvalidInput as exc:
            invalid, status = exc.form, 400
        except signing.BadSignature:
            error, status = "انتهت صلاحية الطلب أو تغيّر محتواه. حدّث الصفحة وحاول مجددًا.", 400
        except WorkflowConflict as exc:
            error, status = str(exc), 409
        except IntegrityError:
            error, status = "تغيّرت البيانات قبل الحفظ. حدّث الصفحة وحاول مجددًا.", 409

    children = list(assignments(partnership, agreement).select_related('clause', 'updated_by'))
    def form_for(form):
        return invalid if type(invalid) is type(form) and invalid.prefix == form.prefix else form
    rows = [(row, form_for(ProgressForm(initial={"responsibility": row.responsibility, "progress": row.progress}, prefix=f"row-{row.pk}")),
             token(request.user, partnership, agreement, kind="row", row=row.pk, version=row.version)) for row in children]
    agreements = partnership.agreements.annotate(clause_count=Count("clause_assignments"), clause_total=Sum("clause_assignments__progress")) if not agreement else []
    for item in agreements:
        item.progress = mean_progress(item.clause_total, item.clause_count)
    heading = "بطاقة متابعة الاتفاقية" if agreement else "الاتفاقيات وبنود الشراكة"
    name = request.user.get_short_name() or request.user.get_username()
    context = {"page_heading": heading, "display_name": name, "avatar_initial": name[:1], "active_page": "partnerships",
               "partnership": partnership, "agreement": agreement, "rows": rows, "agreements": agreements,
               "progress": mean_progress(sum(row.progress for row in children), len(children)),
               "overall": partnership_progress(partnership) if not agreement else None,
               "title_form": form_for(AgreementTitleForm(prefix="main", initial={"title": agreement.title if agreement else ""})),
               "assign_form": form_for(AssignForm(assigned=[row.clause_id for row in children])),
               "title_token": token(request.user, partnership, agreement, kind="title", title=agreement.title if agreement else ""),
               "add_token": token(request.user, partnership, agreement, kind="add"), "error": error}
    if agreement:
        context.update(followup_context(request, partnership, agreement, children, **followup_errors))
    return add_login_headers(render(request, "agreement_clauses/workflow.html", context, status=status))
