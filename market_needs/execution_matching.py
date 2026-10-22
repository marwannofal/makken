"""Execution eligibility, deliberately independent of financial sponsor matching."""
from django.db.models import Count, DecimalField, F, OuterRef, Prefetch, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from partnerships.models import Partnership, PartnershipOffering
from service_providers.models import ServiceProvider, ProviderCoverage
from .models import Need, NeedStatus, Sponsorship, SponsorshipStatus


def approved_needs():
    money = DecimalField(max_digits=16, decimal_places=2)
    funding = Sponsorship.objects.filter(need_id=OuterRef("pk"), status=SponsorshipStatus.APPROVED).order_by().values("need_id").annotate(total=Sum("amount"))
    return (Need.objects.select_related("sector", "specialization", "program", "execution")
            .prefetch_related("regions")
            .annotate(actual_support=Coalesce(Subquery(funding.values("total")[:1]), Value(0), output_field=money),
                      approved_count=Count("sponsorships", filter=Q(sponsorships__status=SponsorshipStatus.APPROVED), distinct=True))
            .filter(status=NeedStatus.COMPLETE, approved_support=F("total_cost"), actual_support=F("total_cost")))


def matching_coverage(need):
    return ProviderCoverage.objects.filter(
        is_active=True, region__is_active=True, region__market_needs=need,
        specializations=need.specialization_id,
        specializations__is_active=True, specializations__sector_id=need.sector_id,
        specializations__sector__is_active=True,
    ).select_related("region").distinct()


def providers(need):
    if not need.is_active or not need.program.is_active or not need.sector.is_active or not need.specialization.is_active:
        return ServiceProvider.objects.none()
    return (ServiceProvider.objects.filter(is_active=True, program_id=need.program_id,
                                          coverage__in=matching_coverage(need))
            .select_related("program")
            .prefetch_related(Prefetch("coverage", queryset=matching_coverage(need), to_attr="matched_coverage"))
            .distinct().order_by("name", "pk"))


def employment_offerings(need):
    return PartnershipOffering.objects.filter(
        is_active=True, sector_id=need.sector_id, sector__is_active=True,
        specializations=need.specialization_id, specializations__is_active=True,
        specializations__sector_id=need.sector_id,
        sponsorship_shape__is_active=True, sponsorship_shape__is_employment=True,
    ).select_related("sponsorship_shape").distinct()


def employers(need):
    if need.training_type != "تشغيلي" or not need.is_active or not need.program.is_active or not need.sector.is_active or not need.specialization.is_active:
        return Partnership.objects.none()
    # Product decision: no partnership geographic filtering; scope is not coverage.
    return (Partnership.objects.filter(is_active=True, entity__is_active=True, offerings__in=employment_offerings(need))
            .select_related("entity", "development_state")
            .prefetch_related(Prefetch("offerings", queryset=employment_offerings(need), to_attr="matched_offerings"))
            .distinct().order_by("name", "pk"))


def provider_evidence(need, provider):
    matched = list(provider.matched_coverage)
    required = {r.pk for r in need.regions.all()}
    return {"name": provider.name, "program": need.program_name,
            "specialization": need.specialization.name,
            "regions": [{"id": row.region_id, "name": row.region.name} for row in matched],
            "full_coverage": required.issubset({row.region_id for row in matched})}


def employer_evidence(need, organization):
    return {"name": organization.name, "sector": need.sector.name,
            "specialization": need.specialization.name,
            "offerings": [{"id": o.pk, "shape": o.sponsorship_shape.name} for o in organization.matched_offerings],
            "geography": "التغطية الجغرافية غير محددة؛ لا يطبق فلتر مناطق على جهات التوظيف."}
