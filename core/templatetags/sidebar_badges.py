"""Request-cached sidebar counter badges for New Sponsor Requests and New Work Assignments."""
from __future__ import annotations

from django import template
from django.apps import apps
from django.db.models import Q, Subquery

register = template.Library()


def format_badge_count(count: int) -> str:
    if not count or count <= 0:
        return ""
    return "99+" if count > 99 else str(count)


def _count_new_sponsor_requests(request) -> int:
    from access_control.policy import for_request
    from partnerships.models import SponsorRequestStatus
    from partnerships.sponsor_requests import _scoped_requests

    policy = for_request(request)
    if not policy.can("sponsor_requests", "view"):
        return 0
    return _scoped_requests(request.user).filter(status=SponsorRequestStatus.NEW).count()


def _count_new_work_assignments(request) -> int:
    from access_control.policy import for_request
    from access_control.regions import scoped
    from makken_mail.models import WorkAssignment, WorkStatus
    from makken_mail.targets import WORK_TARGETS
    from partnerships.models import Partnership

    user = request.user
    query = WorkAssignment.objects.filter(status=WorkStatus.NEW)
    if not user.is_superuser:
        policy = for_request(request)
        participates = Q(employee=user) | Q(assignees=user) | Q(manager=user)
        if policy.can("work_assignments", "create") or policy.can("work_assignments", "edit"):
            participates |= Q(created_by=user)
        query = query.filter(participates)

        visible = Q(target_model="")
        for model, spec in WORK_TARGETS.items():
            if policy.can(spec.module):
                if model == "agreement_clauses.agreement":
                    from agreement_clauses.models import Agreement
                    p_ids = scoped(Partnership._base_manager.all(), user).order_by().values("pk")
                    ids = Agreement._base_manager.filter(partnership_id__in=Subquery(p_ids)).order_by().values("pk")
                else:
                    ids = scoped(apps.get_model(model)._base_manager.all(), user).order_by().values("pk")
                visible |= Q(target_model=model, target_key__in=Subquery(ids))
        query = query.filter(visible).distinct()
    return query.count()


def get_sidebar_new_counts(request) -> dict[str, int | str]:
    """Compute and cache per-request live counts for the two sidebar badges."""
    if not request or not getattr(request, "user", None) or not request.user.is_authenticated:
        return {
            "sponsor_requests_new": 0,
            "sponsor_requests_display": "",
            "work_assignments_new": 0,
            "work_assignments_display": "",
        }

    cached = getattr(request, "_makken_sidebar_badges", None)
    if cached is not None:
        return cached

    sponsor_new = _count_new_sponsor_requests(request)
    work_new = _count_new_work_assignments(request)
    result = {
        "sponsor_requests_new": sponsor_new,
        "sponsor_requests_display": format_badge_count(sponsor_new),
        "work_assignments_new": work_new,
        "work_assignments_display": format_badge_count(work_new),
    }
    request._makken_sidebar_badges = result
    return result


@register.simple_tag(takes_context=True)
def sidebar_new_counts(context):
    return get_sidebar_new_counts(context.get("request"))
