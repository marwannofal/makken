"""Permission-scoped ORM analytics. No business writes and no cross-request cache.

Money is aggregated once per need, via a correlated contribution subquery.
Named counterparties have independent source-page and regional boundaries.
"""
from decimal import Decimal, ROUND_HALF_UP
from datetime import timezone as dt_timezone, timedelta
from django.db.models import (Q, F, Sum, Count, Max, Subquery, OuterRef, Exists,
                             Value, DecimalField, IntegerField, Case, When)
from django.db.models.functions import Coalesce, TruncMonth
from django.utils import timezone
from django.utils.functional import cached_property
from access_control.policy import AccessPolicy
from access_control.regions import RegionalPolicy, scoped
from access_control.activity_data import audit_timezone
from market_needs.models import Need, NeedRegion, Sponsorship, NeedExecution, ExecutionProvider, ExecutionEmployer
from partnerships.models import Partnership
from service_providers.models import ServiceProvider
from regions.models import Region
from sectors.models import Sector
from specializations.models import Specialization
from training_programs.models import TrainingProgram
from .dashboard_filters import DashboardFilterForm, during

ZERO = Decimal('0.00')
SQL_TZ = dt_timezone(timedelta(hours=3))
MONEY = DecimalField(max_digits=24, decimal_places=2)
RANKS = {'strategic':4, 'gold':3, 'silver':2, 'bronze':1}
LEVEL_LABELS = {4:'استراتيجي',3:'ذهبي',2:'فضي',1:'برونزي',0:'غير مصنف'}
STATE_LABELS = {'new':'جديد','working':'جاري العمل','complete':'مكتملة الدعم','rejected':'تم الرفض'}


def percent(value, total):
    return (Decimal(value)*100/Decimal(total)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP) if total else ZERO


def money(value):
    return f'{Decimal(value or 0):,.2f}'


def rank_expression():
    return Case(*[When(level__funding_key=key,then=Value(rank)) for key,rank in RANKS.items()],default=Value(0),output_field=IntegerField())


def need_query(user):
    paid = Sponsorship.objects.filter(need_id=OuterRef('pk'),status='approved').order_by().values('need_id')
    total = paid.annotate(value=Sum('amount')).values('value')[:1]
    count = paid.annotate(value=Count('pk')).values('value')[:1]
    areas = NeedRegion.objects.filter(need_id=OuterRef('pk')).order_by().values('need_id')
    area_count = areas.annotate(value=Count('pk')).values('value')[:1]
    first_area = NeedRegion.objects.filter(need_id=OuterRef('pk')).order_by('region_id').values('region_id')[:1]
    return scoped(Need.objects.all(),user).annotate(
        cash=Coalesce(Subquery(total,output_field=MONEY),Value(ZERO),output_field=MONEY),
        contributors=Coalesce(Subquery(count,output_field=IntegerField()),Value(0)),
        area_count=Coalesce(Subquery(area_count,output_field=IntegerField()),Value(0)),
        sole_region=Subquery(first_area,output_field=IntegerField()))


class Dashboard:
    def __init__(self, user, params, now=None):
        self.user, self.params = user, params
        self.generated_at = now or timezone.now()
        self.policy, self.region_policy = AccessPolicy(user), RegionalPolicy(user)
        self.market = self.policy.can('market_needs')
        self.execution = self.policy.can('approved_programs') or self.policy.can('provider_assignments')
        self.organizations = self.market and self.policy.can('partnerships')
        self.providers = self.execution and self.policy.can('service_providers')
        self.activity = self.policy.can('user_activity')
        base = need_query(user) if self.market or self.execution else Need.objects.none()
        if not self.market and self.execution:
            base = self.eligible(base)
        self.allowed_regions = scoped(Region.objects.all(),policy=self.region_policy)
        choices = {'regions':self.allowed_regions.values_list('pk','name')}
        for key,model in [('sector',Sector),('specialization',Specialization),('program',TrainingProgram)]:
            choices[key] = model.objects.filter(pk__in=base.values(key+'_id')).values_list('pk','name')
        pairs = list(base.order_by().values_list('sector_id','specialization_id').distinct())
        self.pairs = pairs
        self.form = DashboardFilterForm(params,choices=choices,pairs=pairs,now=self.generated_at)
        self.valid = self.form.is_valid()
        self.filters = self.form.cleaned_data if self.valid else {}
        self.structural = self.apply(base) if self.valid else base.none()
        self.needs = during(self.structural,'created_at',self.filters).order_by('-pk')

    @staticmethod
    def eligible(query):
        # The same financial gate as approved_needs(): never advance a stale
        # cached status or consider a partially funded card ready to execute.
        return query.filter(status='complete',approved_support=F('total_cost'),cash=F('total_cost'))

    def apply(self, query):
        data = self.filters
        if data.get('regions'):
            query = query.filter(pk__in=NeedRegion.objects.filter(region_id__in=data['regions']).values('need_id'))
        for key in ('sector','specialization','program','training_type'):
            if data.get(key):query=query.filter(**{key:data[key]})
        if data.get('activation') in {'0','1'}:
            query=query.filter(is_active=data['activation']=='1')
        return query

    @cached_property
    def summary(self):
        if not self.market:return None
        data = self.needs.aggregate(cards=Count('pk'),programs=Count('program_id',distinct=True),
            active=Count('pk',filter=Q(is_active=True)),inactive=Count('pk',filter=Q(is_active=False)),
            new=Count('pk',filter=Q(status='new')),working=Count('pk',filter=Q(status='working')),
            complete=Count('pk',filter=Q(status='complete')),rejected=Count('pk',filter=Q(status='rejected')),
            unfunded=Count('pk',filter=Q(cash=0)),partial=Count('pk',filter=Q(cash__gt=0,cash__lt=F('total_cost'))),
            beneficiaries=Sum('beneficiaries'),cost=Sum('total_cost'),requested=Sum('requested_support'),
            approved=Sum('cash'),shared=Count('pk',filter=Q(area_count__gt=1)),
            mismatch=Count('pk',filter=~Q(approved_support=F('cash'))))
        for key in ('cost','requested','approved'):data[key]=data[key] or ZERO
        data['beneficiaries']=data['beneficiaries'] or 0
        data['remaining']=data['cost']-data['approved']
        data['percentage']=percent(data['approved'],data['cost'])
        return data

    @cached_property
    def funded(self):
        return self.eligible(self.needs)

    @cached_property
    def execution_summary(self):
        if not self.execution:return None
        query = self.funded.annotate(has_provider=Exists(ExecutionProvider.objects.filter(execution__need_id=OuterRef('pk'))))
        new = Q(execution__isnull=True)|Q(execution__status='new')
        data=query.aggregate(total=Count('pk'),new=Count('pk',filter=new),
            waiting=Count('pk',filter=new&Q(has_provider=False,is_active=True)),
            running=Count('pk',filter=Q(execution__status='running')),
            complete=Count('pk',filter=Q(execution__status='complete')),
            running_beneficiaries=Sum('beneficiaries',filter=Q(execution__status='running')),
            completed_beneficiaries=Sum('beneficiaries',filter=Q(execution__status='complete')))
        data['percentage']=percent(data['complete'],data['total'])
        data['running_beneficiaries']=data['running_beneficiaries'] or 0
        data['completed_beneficiaries']=data['completed_beneficiaries'] or 0
        return data

    @cached_property
    def waiting_cards(self):
        return self.funded.annotate(has_provider=Exists(ExecutionProvider.objects.filter(
            execution__need_id=OuterRef('pk')))).filter(
                Q(execution__isnull=True)|Q(execution__status='new'),
                is_active=True,has_provider=False)

    @cached_property
    def underfunded_cards(self):
        return self.needs.filter(is_active=True,status__in=['new','working'],cash__lt=F('total_cost'))

    @cached_property
    def contributions(self):
        return Sponsorship.objects.filter(need_id__in=self.needs.values('pk'),status='approved') if self.market else Sponsorship.objects.none()

    @cached_property
    def visible_partners(self):
        if not self.organizations:return Partnership.objects.none()
        # Actual candidate/sponsor relationships, not a sector-based guess.
        return scoped(Partnership.objects.all(),self.user).filter(pk__in=
            Sponsorship.objects.filter(need_id__in=self.needs.values('pk')).values('partnership_id'))

    @cached_property
    def named_contributions(self):
        return self.contributions.filter(partnership_id__in=self.visible_partners.values('pk'))

    @cached_property
    def ranked_partners(self):
        best=self.named_contributions.filter(partnership_id=OuterRef('pk')).annotate(
            rank=rank_expression()).order_by('-rank','-pk')
        return self.visible_partners.filter(pk__in=self.named_contributions.values('partnership_id')).annotate(
            best_rank=Subquery(best.values('rank')[:1]),
            best_label=Subquery(best.values('level_name')[:1]))

    def donor_rows(self, limit=10):
        if not self.organizations:return []
        grouped=self.named_contributions.filter(partnership_id=OuterRef('pk')).order_by().values('partnership_id').annotate(
            cards=Count('need_id',distinct=True),amount=Sum('amount'))
        query=self.ranked_partners.annotate(cards=Subquery(grouped.values('cards')[:1]),
            amount=Subquery(grouped.values('amount')[:1],output_field=MONEY)).order_by('-amount','pk')
        return [{'partnership_id':r['pk'],'partnership__name':r['name'],'cards':r['cards'],
                 'amount':r['amount'],'rank':r['best_rank'],'snapshot_label':r['best_label']}
                for r in query.values('pk','name','cards','amount','best_rank','best_label')[:limit]]

    @cached_property
    def organization_summary(self):
        if not self.organizations:return None
        states=self.visible_partners.aggregate(total=Count('pk'),
            capability=Count('pk',filter=Q(development_state_id='capability')),
            willingness=Count('pk',filter=Q(development_state_id='willingness')),
            care=Count('pk',filter=Q(development_state_id='care')))
        levels=self.ranked_partners.aggregate(**{'level_'+str(rank):Count('pk',filter=Q(best_rank=rank)) for rank in range(5)})
        states.update(levels)
        states['sponsors']=self.ranked_partners.count()
        return states

    @cached_property
    def provider_query(self):
        if not self.providers:return ServiceProvider.objects.none()
        links=ExecutionProvider.objects.filter(execution__need_id__in=self.funded.values('pk'))
        return scoped(ServiceProvider.objects.all(),self.user).filter(pk__in=links.values('provider_id'))

    def provider_rows(self, limit=10):
        if not self.providers:return []
        # Unique execution/provider pairs ensure SUM does not multiply seats.
        query=ExecutionProvider.objects.filter(execution__need_id__in=self.funded.values('pk'),
            provider_id__in=self.provider_query.values('pk')).order_by().values('provider_id','provider__name','provider__is_active').annotate(
                cards=Count('execution__need_id',distinct=True),programs=Count('execution__need__program_id',distinct=True),
                new=Count('pk',filter=Q(execution__status='new')),
                running=Count('pk',filter=Q(execution__status='running')),
                complete=Count('pk',filter=Q(execution__status='complete')),
                beneficiaries=Sum('execution__need__beneficiaries')).order_by('-complete','-cards','provider_id')
        return list(query[:limit])

    @cached_property
    def employer_count(self):
        if not self.execution or not self.policy.can('partnerships'):return None
        ids=ExecutionEmployer.objects.filter(execution__need_id__in=self.funded.values('pk')).values('partnership_id')
        return scoped(Partnership.objects.all(),self.user).filter(pk__in=ids).count()

    @cached_property
    def financial_regions(self):
        if not self.market:return []
        rows=[]
        singles=self.needs.filter(area_count=1).order_by().values('regions__pk','regions__name').annotate(
            cards=Count('pk'),beneficiaries=Sum('beneficiaries'),cost=Sum('total_cost'),approved=Sum('cash')).order_by('regions__pk')
        for row in singles:
            rows.append({**row,'bucket':row['regions__pk'],'name':row['regions__name']})
        for condition,key,name in [(Q(area_count__gt=1),-2,'مشترك بين مناطق'),(Q(area_count=0),-1,'غير محدد المنطقة')]:
            row=self.needs.filter(condition).aggregate(cards=Count('pk'),beneficiaries=Sum('beneficiaries'),
                cost=Sum('total_cost'),approved=Sum('cash'))
            if row['cards']:rows.append({**row,'bucket':key,'name':name})
        return rows

    @cached_property
    def region_rows(self):
        if not (self.market or self.execution):return []
        visible_areas=self.allowed_regions
        if self.filters.get('regions'):visible_areas=visible_areas.filter(pk__in=self.filters['regions'])
        query=self.needs.filter(regions__in=visible_areas).order_by().values('regions__pk','regions__name')
        measures={'cards':Count('pk',distinct=True),'beneficiaries':Sum('beneficiaries')}
        if self.market:
            measures.update({key:Count('pk',filter=Q(status=key)) for key in STATE_LABELS})
        if self.execution:
            measures['running']=Count('pk',filter=Q(pk__in=self.funded.values('pk'),execution__status='running'))
            measures['executed']=Count('pk',filter=Q(pk__in=self.funded.values('pk'),execution__status='complete'))
        return list(query.annotate(**measures).order_by('regions__pk'))

    @cached_property
    def sector_rows(self):
        if not self.market:return []
        return list(self.needs.order_by().values('sector_id','sector__name').annotate(
            cards=Count('pk'),beneficiaries=Sum('beneficiaries')).order_by('-beneficiaries','sector_id'))

    @cached_property
    def monthly_cards(self):
        if not self.market:return []
        return list(self.needs.annotate(month=TruncMonth('created_at',tzinfo=SQL_TZ)).order_by().values('month').annotate(value=Count('pk')).order_by('month'))

    @cached_property
    def monthly_support(self):
        if not self.market:return []
        events=Sponsorship.objects.filter(need_id__in=self.structural.values('pk'),status='approved',decided_at__isnull=False)
        return list(during(events,'decided_at',self.filters).annotate(month=TruncMonth('decided_at',tzinfo=SQL_TZ))
            .order_by().values('month').annotate(value=Sum('amount')).order_by('month'))

    @cached_property
    def missing_approval_dates(self):
        if not self.market:return 0
        return Sponsorship.objects.filter(need_id__in=self.structural.values('pk'),status='approved',decided_at=None).count()

    @cached_property
    def arrangement(self):
        if not self.market:return None
        return self.needs.aggregate(alliance=Count('pk',filter=Q(contributors__gt=1)),
            individual=Count('pk',filter=Q(contributors=1,cash=F('total_cost'))),
            partial=Count('pk',filter=Q(contributors=1,cash__lt=F('total_cost'))),
            none=Count('pk',filter=Q(contributors=0)))

    @cached_property
    def completion_months(self):
        if not self.execution:return []
        events=NeedExecution.objects.filter(need_id__in=self.eligible(self.structural).values('pk'),status='complete',completed_at__isnull=False)
        return list(during(events,'completed_at',self.filters).annotate(month=TruncMonth('completed_at',tzinfo=SQL_TZ))
            .order_by().values('month').annotate(value=Count('pk')).order_by('month'))

    @cached_property
    def recent_activity(self):
        if not self.activity or not self.valid:return []
        from access_control.activity_data import visible_events, decorate_event
        query=visible_events(self.user)
        if self.filters.get('regions'):
            query=query.filter(region_snapshots__region_key__in=self.filters['regions']).distinct()
        return [decorate_event(e) for e in during(query,'created_at',self.filters).prefetch_related('region_snapshots')[:6]]
