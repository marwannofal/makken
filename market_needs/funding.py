"""Exact contribution bands and expense funding; never invent legacy allocations."""
from decimal import Decimal
from django.db.models import Sum, Q
from care_states.models import DevelopmentState, StateColor
from .models import SponsorshipStatus, percentage


def level_key(amount, total):
    if amount <= 0 or total <= 0:
        return None
    if amount == total:
        return "strategic"
    if amount * 100 >= total * 80:
        return "gold"
    if amount * 100 >= total * 60:
        return "silver"
    return "bronze"


def expense_funding(need):
    lines = list(need.expense_lines.select_related("expense_item", "sponsorship_shape").annotate(
        funded=Sum("funding_allocations__amount", filter=Q(funding_allocations__sponsorship__status=SponsorshipStatus.APPROVED)),
    ))
    for line in lines:
        line.approved_amount = (line.funded or Decimal("0.00")).quantize(Decimal(".01"))
        line.remaining_amount = line.amount - line.approved_amount
        line.coverage_percent = percentage(line.approved_amount, line.amount)
    return lines


def development_timeline(organization):
    dates = {entry.state_id: entry.entered_at for entry in organization.development_history.all()}
    # Older imports may have only a current entry timestamp. It is a known date,
    # not a fabricated intermediate transition.
    dates.setdefault(organization.development_state_id, organization.development_state_at)
    colors = StateColor.objects.in_bulk()
    return [{"label": label, "date": dates.get(key), "current": organization.development_state_id == key,
             "color": colors[key].color if key in colors else "#74888b"} for key, label in DevelopmentState.choices]
