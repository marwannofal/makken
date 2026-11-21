"""Readable dashboard/chart/report data, independent of HTML and chart libraries."""
from decimal import Decimal
from urllib.parse import urlencode
from django.urls import reverse
from .dashboard_data import money, percent, STATE_LABELS, LEVEL_LABELS

COLORS = ['#005b85','#E0AC50','#6F9AB9','#C76F72','#8F8CB1']


def link(report, kind, **extra):
    params=report.params.copy()
    for key in ('page','_mk_export','_mk_table','state','funding','execution','level','bucket'):
        params.pop(key,None)
    for key,value in extra.items():
        if isinstance(value,list):params.setlist(key,[str(v) for v in value])
        else:params[key]=str(value)
    return reverse('core:dashboard_records',kwargs={'kind':kind})+'?'+params.urlencode()


def bar_chart(slug,title,caption,rows,headers,*,unit='',limit=10):
    maximum=max((max(r['value'],r.get('second',0)) for r in rows),default=0)
    for row in rows:
        row['width']=str(percent(row['value'],maximum))
        row['display']=money(row['value']) if unit=='ريال' else f'{int(row["value"]):,}'
        if 'second' in row:
            row['second_width']=str(percent(row['second'],maximum))
            row['second_display']=money(row['second'])
        row.setdefault('cells',[row['label'],row['display']+(' '+unit if unit else '')])
    return {'slug':slug,'title':title,'caption':caption,'rows':rows[:limit], 'all_rows':rows,
            'headers':headers,'unit':unit,'has_data':bool(rows) and maximum>0,
            'more':len(rows)>limit,'kind':'bars'}


def donut(slug,title,caption,items):
    total=sum(row['value'] for row in items)
    stop=Decimal('0');parts=[]
    for index,row in enumerate(items):
        share=percent(row['value'],total);end=min(Decimal('100'),stop+share)
        row.update(color=row.get('color',COLORS[index%len(COLORS)]),share=share,dash=str(share),offset=str(-stop),
                   display=f'{row["value"]:,}',cells=[row['label'],str(row['value']),str(share)+'%'])
        parts.append(f'{row["color"]} {stop}% {end}%');stop=end
    return {'slug':slug,'title':title,'caption':caption,'rows':items,'all_rows':items,
            'headers':['الحالة','العدد','النسبة'],'gradient':', '.join(parts) if total else '#e9f2f1 0% 100%',
            'total':total,'has_data':total>0,'kind':'donut'}


def build_charts(report):
    charts=[]
    if report.market:
        summary=report.summary
        charts.append(donut('funding-states','حالات بطاقات السوق','الحالة الحالية للبطاقات المنشأة ضمن الفترة المختارة.',[
            {'label':label,'value':summary[key],'href':link(report,'cards',state=key)} for key,label in STATE_LABELS.items()]))
        charts.append(bar_chart('region-cards','البطاقات حسب المنطقة','قد تظهر البطاقة المشتركة في أكثر من منطقة؛ لا تجمع هذه الأعداد لإيجاد الإجمالي الفريد.',[
            {'label':r['regions__name'],'value':r['cards'],'href':link(report,'cards',regions=[r['regions__pk']]),
             'cells':[r['regions__name'],str(r['cards']),str(r['new']),str(r['working']),str(r['complete']),str(r['rejected'])]}
            for r in report.region_rows],['المنطقة','البطاقات','جديد','جاري العمل','مكتملة الدعم','تم الرفض']))
        charts.append(bar_chart('region-money','التكلفة والدعم حسب المنطقة','تركوازي: التكلفة · أزرق: الدعم المعتمد. التمويل المشترك يظهر مرة واحدة في بند مستقل.',[
            {'label':r['name'],'value':r['cost'],'second':r['approved'],
             'href':link(report,'cards',bucket=r['bucket']),
             'cells':[r['name'],money(r['cost'])+' ريال',money(r['approved'])+' ريال']}
            for r in report.financial_regions],['الإسناد الجغرافي','التكلفة','الدعم المعتمد'],unit='ريال'))
        charts.append(bar_chart('sector-beneficiaries','المستهدفون حسب القطاع','مجموع أعداد المستفيدين المسجلة على البطاقات، وليس عدد أشخاص فريدين.',[
            {'label':r['sector__name'],'value':r['beneficiaries'],'href':link(report,'cards',sector=r['sector_id'],specialization='')}
            for r in report.sector_rows],['القطاع','المستفيدون المستهدفون']))
        charts.append(bar_chart('region-beneficiaries','المستهدفون حسب المنطقة','أعداد مستهدفة في البطاقات. البطاقة المشتركة تظهر في كل منطقة مرتبطة بها؛ الصفوف غير قابلة للجمع لإيجاد عدد فريد.',[
            {'label':r['regions__name'],'value':r['beneficiaries'],'href':link(report,'cards',regions=[r['regions__pk']])}
            for r in report.region_rows],['المنطقة','المستفيدون المستهدفون']))
        charts.append(bar_chart('monthly-cards','إنشاء البطاقات عبر الأشهر','يعتمد تاريخ إنشاء البطاقة بتوقيت الرياض؛ تظهر أحدث 18 شهرًا، وبيانات الرسم الكاملة متاحة.',[
            {'label':r['month'].strftime('%Y-%m'),'value':r['value']} for r in report.monthly_cards][-18:],['الشهر','البطاقات'],limit=18))
        charts[-1]['all_rows']=[{'cells':[r['month'].strftime('%Y-%m'),str(r['value'])]} for r in report.monthly_cards]
        charts.append(bar_chart('monthly-support','اعتماد الدعم عبر الأشهر','يعتمد تاريخ اعتماد المساهمة، لجميع البطاقات المطابقة للفلاتر الموضوعية، ولو أُنشئت قبل الفترة. أحدث 18 شهرًا مع جدول كامل.',[
            {'label':r['month'].strftime('%Y-%m'),'value':r['value']} for r in report.monthly_support][-18:],['شهر الاعتماد','الدعم المعتمد'],unit='ريال',limit=18))
        charts[-1]['all_rows']=[{'cells':[r['month'].strftime('%Y-%m'),money(r['value'])+' ريال']} for r in report.monthly_support]
        charts.append(donut('arrangements','كيف تتوزع الرعاية؟','الفردي يعني جهة واحدة غطّت كامل التكلفة؛ المساهمة الواحدة الجزئية تظهر بصورة مستقلة.',[
            {'label':label,'value':report.arrangement[key]} for key,label in [('individual','فردي مكتمل'),('alliance','تحالف'),('partial','مساهمة واحدة جزئية'),('none','بلا دعم معتمد')]]))
    if report.execution:
        data=report.execution_summary
        charts.append(donut('execution-states','حالات التنفيذ','الحالة الحالية للبطاقات المؤهلة ماليًا ضمن مجموعة البطاقات المختارة؛ اكتمال التنفيذ مستقل عن اكتمال الدعم.',[
            {'label':label,'value':data[key],'href':link(report,'executions',execution=key)}
            for key,label in [('new','لم يبدأ التنفيذ'),('running','تحت التنفيذ'),('complete','مكتمل التنفيذ')]]))
        charts.append(bar_chart('completed-months','اكتمال التنفيذ عبر الأشهر','يعتمد تاريخ اكتمال التنفيذ الفعلي، لا تاريخ آخر تعديل. تطبّق فلاتر الموضوع والمنطقة والفترة على حدث الاكتمال.',[
            {'label':r['month'].strftime('%Y-%m'),'value':r['value']} for r in report.completion_months][-18:],['شهر الاكتمال','بطاقات مكتملة التنفيذ'],limit=18))
        charts[-1]['all_rows']=[{'cells':[r['month'].strftime('%Y-%m'),str(r['value'])]} for r in report.completion_months]
    if report.organizations:
        counts=report.organization_summary
        from care_states.models import StateColor
        import re
        colors={r.state:r.color for r in StateColor.objects.all() if re.fullmatch(r'#[0-9a-fA-F]{6}',r.color)}
        charts.append(donut('partner-states','حالات الجهات المرتبطة بالبطاقات','حالات الجهات المرشحة أو الممولة المرتبطة بالبطاقات المختارة، وليست نتيجة بحث المطابقة أو إجمالي جهات النظام.',[
            {'label':label,'value':counts[key],'color':colors.get(key,COLORS[index]),'href':link(report,'partners',state=key)}
            for index,(key,label) in enumerate([('capability','قدرة'),('willingness','رغبة'),('care','رعاية')])]))
        charts.append(bar_chart('sponsor-levels','الجهات حسب أعلى مستوى رعاية','تُحتسب كل جهة مرة واحدة حسب أعلى مستوى محفوظ لمساهماتها المعتمدة في البطاقات المختارة.',[
            {'label':label,'value':counts['level_'+str(rank)],'href':link(report,'donors',level=rank)}
            for rank,label in LEVEL_LABELS.items()],['المستوى','عدد الجهات']))
    return charts


def report_table(report, charts, limit):
    """One complete, branded multi-section report, not a scraped preview table."""
    from core.export_tables import Table
    from core.export_tables import ExportError
    rows=[]
    def add(section,label,details,value='',unit=''):
        rows.append([[str(section)],[str(label)],[str(details)],[str(value)],[str(unit)]])
        if len(rows)>limit:raise ExportError('التقرير كبير جدًا. ضيّق الفلاتر ثم أعد التصدير.',413)
    if report.market:
        for key,label,unit in [('cards','البطاقات','بطاقة'),('programs','البرامج التدريبية المختلفة','برنامج'),
            ('active','بطاقات نشطة','بطاقة'),('inactive','بطاقات غير نشطة','بطاقة'),
            ('new','جديد','بطاقة'),('working','جاري العمل','بطاقة'),('complete','مكتملة الدعم','بطاقة'),('rejected','تم الرفض','بطاقة'),
            ('unfunded','بلا تمويل','بطاقة'),('partial','تمويل جزئي','بطاقة'),
            ('beneficiaries','المستفيدون المستهدفون','مقعد مستهدف'),('cost','تكلفة الاحتياجات','ريال'),
            ('requested','الدعم المطلوب','ريال'),('approved','الدعم المعتمد','ريال'),('remaining','المتبقي','ريال'),('percentage','نسبة التغطية','%')]:
            value=report.summary[key]
            add('ملخص البطاقات',label,'حالة حالية للبطاقات المنشأة ضمن الفترة',money(value) if unit=='ريال' else str(value),unit)
    else:add('ملخص البطاقات','غير متاح','يتطلب صلاحية بطاقات حاجة السوق')
    if report.execution:
        for key,label in [('total','بطاقات مؤهلة للتنفيذ'),('waiting','تنتظر اختيار مزود'),('new','لم يبدأ التنفيذ'),
            ('running','تحت التنفيذ'),('complete','مكتمل التنفيذ'),('running_beneficiaries','المستهدفون في التنفيذ الجاري'),
            ('completed_beneficiaries','المستهدفون في التنفيذ المكتمل'),('percentage','نسبة اكتمال التنفيذ')]:
            add('التنفيذ',label,'النسبة من عدد البطاقات المؤهلة ماليًا',report.execution_summary[key], '%' if key=='percentage' else '')
    for chart in charts:
        for row in chart['all_rows']:
            cells=row['cells']
            add(chart['title'],cells[0], ' · '.join(f'{h}: {v}' for h,v in zip(chart['headers'][1:],cells[1:])))
    if report.organizations:
        donors=report.donor_rows(limit+1)
        if len(donors)>limit:raise ExportError('عدد الجهات كبير. ضيّق الفلاتر.',413)
        for row in donors:
            add('الجهات الراعية',row['partnership__name'],f'البطاقات: {row["cards"]} · المستوى المحفوظ: {row["snapshot_label"] or LEVEL_LABELS[row["rank"]]}',money(row['amount']),'ريال')
    if report.providers:
        providers=report.provider_rows(limit+1)
        if len(providers)>limit:raise ExportError('عدد المزودين كبير. ضيّق الفلاتر.',413)
        for row in providers:
            add('مزودو التدريب',row['provider__name'],f'جديد: {row["new"]} · جاري: {row["running"]} · مكتمل: {row["complete"]} · مستهدفون: {row["beneficiaries"]}',row['cards'],'بطاقة مسندة')
    if report.market:
        for row in report.underfunded_cards.iterator(chunk_size=500):
            add('احتياجات نشطة تنتظر الدعم',row.title,f'{row.number} · التكلفة: {money(row.total_cost)} · المعتمد: {money(row.cash)}',money(row.total_cost-row.cash),'ريال متبقي')
    if report.execution:
        for row in report.region_rows:
            add('التنفيذ حسب المنطقة',row['regions__name'],f'تحت التنفيذ: {row["running"]} · مكتمل التنفيذ: {row["executed"]}؛ قد تتداخل البطاقة المشتركة بين المناطق')
        for row in report.waiting_cards.iterator(chunk_size=500):
            add('بطاقات نشطة تنتظر مزودًا',row.title,f'{row.number} · {row.program_name}')
    if report.activity:
        # A dashboard export must not bypass the activity module's own export
        # permission. The detailed activity report remains on its source page.
        add('سجل النشاط','تقرير مستقل','تصدير الأنشطة التفصيلية من صفحة سجل النشاط حسب صلاحيات تصديرها المستقلة.')
    add('تعريفات','المستهدفون','مجموع أعداد البطاقات، وليس طلابًا مسجلين فعليًا أو أشخاصًا فريدين.')
    add('تعريفات','الدعم المعتمد','اعتماد مساهمة لا يثبت تحصيل المبلغ نقديًا. التمويل المشترك بين المناطق محسوب مرة واحدة.')
    add('تعريفات','الصلاحيات','المجاميع المالية تخص البطاقات المسموحة. ترتيب الجهات والمزودين يقتصر على الجهات المسموحة، وقد لا يجمع إلى إجمالي التمويل.')
    return Table(['القسم','المؤشر / السجل','التفاصيل','القيمة','الوحدة'],rows,'لوحة متابعة مكّن',None)
