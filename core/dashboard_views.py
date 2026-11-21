from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q, F, Exists, OuterRef
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import content_disposition_header
from django.views.decorators.http import require_GET
from accounts.security import add_login_headers
from access_control.enforcement import module_view, denied
from access_control.policy import require
from access_control.activity_data import audit_timezone
from .dashboard_data import Dashboard, money, LEVEL_LABELS
from .dashboard_presenter import build_charts, link, report_table
from .dashboard_snapshot import consistent_dashboard


def base(request, report):
    name=request.user.get_short_name() or request.user.get_username()
    return {'display_name':name,'avatar_initial':name[:1],'active_page':'home',
            'page_heading':'لوحة المتابعة','dashboard':report,'filter_form':report.form,
            'dashboard_timezone':audit_timezone(),
            'generated_at':timezone.localtime(report.generated_at,audit_timezone())}


def export_url(request,format):
    params=request.GET.copy()
    for key in ('page','_mk_export','_mk_table'):params.pop(key,None)
    return reverse('core:dashboard_export',kwargs={'format':format})+'?'+params.urlencode()


def metric(label,value,detail='',href='',unit=''):
    return {'label':label,'value':money(value) if unit=='ريال' else f'{value:,}',
            'detail':detail,'href':href,'unit':unit}


def context(request,report):
    metrics=[];financial=[]
    if report.market:
        s=report.summary
        metrics.extend([
            metric('بطاقات حاجة السوق',s['cards'],f'نشطة: {s["active"]:,} · غير نشطة: {s["inactive"]:,}',link(report,'cards')),
            metric('المستفيدون المستهدفون',s['beneficiaries'],'مجموع أعداد البطاقات؛ ليس أشخاصًا فريدين',link(report,'cards')),
            metric('برامج تدريبية مختلفة',s['programs'],'عدد البرامج المرجعية دون تكرار',link(report,'cards')),
            metric('بطاقات بتمويل جزئي',s['partial'],'دعم معتمد أكبر من صفر وأقل من التكلفة',link(report,'cards',funding='partial'))])
        financial=[metric(label,s[key],detail,unit='ريال') for key,label,detail in [
            ('cost','إجمالي تكلفة الاحتياجات','تكلفة البطاقات المختارة'),('requested','قيمة الدعم المطلوبة','مبلغ مستقل عن التكلفة الإجمالية'),
            ('approved','الدعم المعتمد','المساهمات المعتمدة طوال عمر البطاقات المختارة'),('remaining','المبلغ المتبقي','التكلفة ناقص الدعم المعتمد')]]
    if report.execution:
        e=report.execution_summary
        metrics.extend([
            metric('تحت التنفيذ',e['running'],f'المستهدفون: {e["running_beneficiaries"]:,}',link(report,'executions',execution='running')),
            metric('مكتملة التنفيذ',e['complete'],f'نسبة الاكتمال: {e["percentage"]}% من {e["total"]:,} بطاقة مؤهلة',link(report,'executions',execution='complete')),
            metric('تنتظر اختيار مزود',e['waiting'],'بطاقات نشطة مكتملة التمويل ولا يوجد مزود مسند',link(report,'executions',execution='waiting')),
            metric('المستهدفون في التنفيذ المكتمل',e['completed_beneficiaries'],'أعداد مستهدفة؛ ليست شهادات تخرّج فعلية',link(report,'executions',execution='complete'))])
    if report.organizations:
        metrics.append(metric('الجهات الراعية الممولة',report.organization_summary['sponsors'],'جهات مسموحة لها مساهمات معتمدة',link(report,'donors')))
    if report.providers:
        metrics.append(metric('مزودو التدريب المسند إليهم',report.provider_query.count(),'إسناد محفوظ فعليًا، وليس ترشيحًا بالمطابقة',link(report,'providers')))
    if report.employer_count is not None:
        metrics.append(metric('جهات التوظيف المشاركة',report.employer_count,'جهات مسموحة مرتبطة بإسناد التنفيذ'))
    needs=[];waiting=[]
    if report.market:
        for n in report.underfunded_cards.select_related('program')[:6]:
            needs.append({'number':n.number,'title':n.title,'cost':money(n.total_cost),'approved':money(n.cash),
                'remaining':money(n.total_cost-n.cash),'href':reverse('market_needs:index')+'?detail='+str(n.pk)})
    if report.execution:
        for n in report.waiting_cards.select_related('program')[:6]:
            destination=reverse('program_execution:assignment',args=[n.pk]) if report.policy.can('provider_assignments') else reverse('program_execution:index')+'?detail='+str(n.pk)
            waiting.append({'number':n.number,'title':n.title,'program':n.program_name,'href':destination})
    donors=report.donor_rows()
    for r in donors:
        r['amount_display']=money(r['amount']);r['level_label']=r['snapshot_label'] or LEVEL_LABELS[r['rank']]
        r['href']=reverse('partnerships:index')+'?detail='+str(r['partnership_id'])
    providers=report.provider_rows()
    for r in providers:r['href']=reverse('service_providers:index')+'?detail='+str(r['provider_id'])
    regional_rows=report.region_rows
    finance_by_region={r['bucket']:r['approved'] for r in report.financial_regions}
    for row in regional_rows:row['owned_approved']=money(finance_by_region.get(row['regions__pk'],0))
    return {**base(request,report),'regional_rows':regional_rows,
            'shared_finance':[r for r in report.financial_regions if r['bucket']<0],'metrics':metrics,'financial_metrics':financial,'charts':build_charts(report),
            'donors':donors,'providers':providers,'underfunded':needs,'waiting':waiting,
            'records_url':link(report,'cards'),'donors_url':link(report,'donors'),'providers_url':link(report,'providers'),
            'waiting_url':link(report,'executions',execution='waiting'),'underfunded_url':link(report,'cards',funding='underfunded'),
            'export_xlsx':export_url(request,'xlsx') if report.policy.can('dashboard','export_xlsx') else '',
            'export_pdf':export_url(request,'pdf') if report.policy.can('dashboard','export_pdf') else ''}


@module_view('dashboard')
@require_GET
@consistent_dashboard
def home(request):
    report=Dashboard(request.user,request.GET)
    return add_login_headers(render(request,'core/makken_home.html',context(request,report)))


@module_view('dashboard')
@require_GET
@consistent_dashboard
def export(request,format):
    from core.export_tables import ExportError
    from core.export_documents import xlsx_bytes,pdf_bytes
    from core.table_exports import EXPORT_LOCK
    if format not in {'xlsx','pdf'}:return JsonResponse({'error':'صيغة التصدير غير مدعومة.'},status=400)
    try:require(request.user,'dashboard','view','export_'+format)
    except PermissionDenied:return denied(request,'لا تملك صلاحية تصدير هذه الصيغة من لوحة المتابعة.')
    if not EXPORT_LOCK.acquire(blocking=False):
        response=JsonResponse({'error':'يوجد تقرير قيد التجهيز. انتظر قليلًا ثم أعد المحاولة.'},status=429)
        response['Retry-After']='20'
        return add_login_headers(response)
    try:
        report=Dashboard(request.user,request.GET)
        if not report.valid:return add_login_headers(JsonResponse({'error':'راجع الفلاتر قبل التصدير. لم يُنشأ تقرير خارج الفلاتر المختارة.'},status=400))
        limit=int(getattr(settings,'MAKKEN_EXPORT_MAX_ROWS',5000))
        if format=='pdf':limit=min(limit,int(getattr(settings,'MAKKEN_PDF_MAX_ROWS',1000)))
        table=report_table(report,build_charts(report),limit)
        filters=[]
        for name,field in report.form.fields.items():
            value=report.form.cleaned_data.get(name)
            if value is None or value=='' or value==[]:continue
            options=dict(field.choices) if hasattr(field,'choices') else {}
            label='، '.join(str(options.get(v,v)) for v in value) if isinstance(value,list) else str(options.get(value,value))
            filters.append(field.label+': '+label)
        filters.append('المؤشرات الأساسية: الوضع الحالي للبطاقات المنشأة ضمن الفترة. الرسوم الحدثية تستخدم تاريخ الاعتماد / الاكتمال بتوقيت الرياض.')
        created=timezone.localtime(report.generated_at,audit_timezone()).strftime('%d/%m/%Y %H:%M:%S UTC+03:00')
        payload=xlsx_bytes(table,' | '.join(filters),created) if format=='xlsx' else pdf_bytes(table,' | '.join(filters),created)
        response=HttpResponse(payload,content_type='application/pdf' if format=='pdf' else 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition']=content_disposition_header(True,'مكّن-لوحة-المتابعة-'+report.generated_at.strftime('%Y%m%d-%H%M')+'.'+format)
        response['Content-Length']=str(len(payload))
        request._dashboard_export_format=format
        return add_login_headers(response)
    except ExportError as error:
        return add_login_headers(JsonResponse({'error':str(error)},status=error.status))
    finally:EXPORT_LOCK.release()


@module_view('dashboard')
@require_GET
@consistent_dashboard
def records(request,kind):
    from market_needs.models import ExecutionProvider
    report=Dashboard(request.user,request.GET)
    permissions={'cards':report.market,'executions':report.execution,'donors':report.organizations,
                 'partners':report.organizations,'providers':report.providers}
    if kind not in permissions:raise Http404
    if not permissions[kind]:return denied(request,'لا تملك صلاحية مصدر هذه البيانات.')
    error=not report.valid;query=report.needs
    title={'cards':'بطاقات السوق المختارة','executions':'متابعة التنفيذ','donors':'الجهات الراعية الممولة',
           'partners':'الجهات المرتبطة بالبطاقات','providers':'مزودو التدريب المسند إليهم'}[kind]
    state=request.GET.get('state','');funding=request.GET.get('funding','')
    execution=request.GET.get('execution','');bucket=request.GET.get('bucket','')
    if kind=='cards':
        if state:
            if state not in {'new','working','complete','rejected'}:error=True
            else:query=query.filter(status=state)
        if funding:
            if funding=='partial':query=query.filter(cash__gt=0,cash__lt=F('total_cost'))
            elif funding=='underfunded':query=report.underfunded_cards
            elif funding=='none':query=query.filter(cash=0)
            else:error=True
        if bucket:
            if bucket=='-2':query=query.filter(area_count__gt=1)
            elif bucket=='-1':query=query.filter(area_count=0)
            elif bucket.isascii() and bucket.isdigit() and len(bucket)<19:
                if not report.allowed_regions.filter(pk=int(bucket)).exists():error=True
                query=query.filter(area_count=1,sole_region=int(bucket))
            else:error=True
    elif kind=='executions':
        query=report.funded
        if execution in {'new','waiting'}:
            query=query.filter(Q(execution__isnull=True)|Q(execution__status='new'))
            if execution=='waiting':query=report.waiting_cards
        elif execution in {'running','complete'}:query=query.filter(execution__status=execution)
        elif execution:error=True
    elif kind=='partners':
        query=report.visible_partners
        if state in {'capability','willingness','care'}:query=query.filter(development_state_id=state)
        elif state:error=True
    elif kind=='donors':
        query=report.ranked_partners;level=request.GET.get('level','')
        if level in {'0','1','2','3','4'}:query=query.filter(best_rank=int(level))
        elif level:error=True
    else:query=report.provider_query
    if error:query=query.none()
    if kind in {'cards','executions'}:query=query.select_related('sector','specialization','program')
    if kind=='executions':query=query.select_related('execution')
    if kind=='partners':query=query.select_related('development_state')
    page=Paginator(query.order_by('-pk'),25).get_page(request.GET.get('page'))
    params=request.GET.copy();params.pop('page',None)
    for row in page:
        if kind in {'cards','executions'}:
            if report.market:row.detail_url=reverse('market_needs:index')+'?detail='+str(row.pk)
            elif report.policy.can('provider_assignments'):row.detail_url=reverse('program_execution:assignment',args=[row.pk])
            else:row.detail_url=reverse('program_execution:index')+'?detail='+str(row.pk)
        elif kind in {'donors','partners'}:row.detail_url=reverse('partnerships:index')+'?detail='+str(row.pk)
        else:row.detail_url=reverse('service_providers:index')+'?detail='+str(row.pk)
    ctx={**base(request,report),'kind':kind,'heading':title,'page_obj':page,'pagination_query':params.urlencode(),
         'back_url':reverse('makken_home')+'?'+link(report,'cards').partition('?')[2], 'filter_error':error}
    return add_login_headers(render(request,'core/dashboard/records.html',ctx,status=400 if error else 200))
