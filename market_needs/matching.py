"""Match partnerships in selectable development states against the card program's required care shapes.

The program supplies expense items/shapes on the saved card. A partnership
supplies sector/specialization/shape offerings; no direct program link exists.
Each offering predicate stays inside ONE EXISTS. Regions are descriptive card
data only, following the owner's 2026-10-18 change to BR-MKT-05 / Appendix C.21.
"""
from dataclasses import dataclass
from django.db.models import Exists, OuterRef, Prefetch, Q
from partnerships.models import Partnership, PartnershipOffering
from care_states.models import DevelopmentState
from training_programs.models import TrainingProgram
from .models import Sponsorship


def matching_offerings(need):
    return PartnershipOffering.objects.filter(
        is_active=True, sector_id=need.sector_id, sector__is_active=True,
        specializations__pk=need.specialization_id, specializations__is_active=True, specializations__sector_id=need.sector_id,
        sponsorship_shape_id__in=need.expense_lines.values("sponsorship_shape_id"),
        sponsorship_shape__is_active=True,
    ).select_related("sector", "sponsorship_shape").distinct()


def eligible_partnerships(need):
    offers = matching_offerings(need).filter(partnership_id=OuterRef("pk"))
    return Partnership.objects.filter(
        Exists(offers), Exists(TrainingProgram.objects.filter(pk=need.program_id, is_active=True)),
        is_active=True, entity__is_active=True,
    )


def candidates(need, filters=None, exclude_linked=True):
    filters = filters or {}
    query = eligible_partnerships(need).filter(development_state_id__in=DevelopmentState.values)
    if exclude_linked:
        query = query.exclude(pk__in=Sponsorship.objects.filter(need=need).values("partnership_id"))
    if filters.get("states"):
        query = query.filter(development_state_id__in=filters["states"])
    if filters.get("scopes"):
        query = query.filter(scope__in=filters["scopes"])
    for word in filters.get("q", "").split()[:12]:
        query = query.filter(Q(name__icontains=word) | Q(representative__icontains=word) | Q(entity__name__icontains=word) | Q(phone__icontains=word) | Q(email__icontains=word))
    return query.select_related("entity", "development_state").prefetch_related(
        Prefetch("offerings", queryset=matching_offerings(need), to_attr="matched_offerings"),
    ).distinct().order_by("name", "pk")


@dataclass
class Match:
    organization: Partnership
    offerings: list
    lines: list
    line_count: int

    @property
    def full(self):
        return len(self.lines) == self.line_count


def eligible_for_approval(need, organization_id):
    # All existing development states are eligible. Actual approval advances
    # capability/willingness directly to care and preserves an existing care date.
    return eligible_partnerships(need).filter(
        pk=organization_id, development_state_id__in=DevelopmentState.values,
    ).exists()



def explain(need, organizations):
    lines = list(need.expense_lines.select_related("expense_item", "sponsorship_shape"))
    result = []
    for organization in organizations:
        shapes = {offering.sponsorship_shape_id for offering in organization.matched_offerings}
        matching = [line for line in lines if line.sponsorship_shape_id in shapes]
        result.append(Match(organization, organization.matched_offerings, matching, len(lines)))
    return result
