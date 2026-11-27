import hashlib
import uuid
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from core.pagination import resolve_page_size
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from access_control.activity_capture import emit
from access_control.enforcement import denied, module_view, superuser_view
from access_control.policy import require_superuser
from accounts.security import add_login_headers
from .forms import ProgressForm, RuleForm, SMTPForm, TestEmailForm, UserPreferenceForm, WorkForm
from .models import Delivery, DeliveryStatus, EventRule, RecipientMute, SMTPConfig, WorkAssignment, WorkStatus
from .registry import CATALOG
from .smtp import REASONS, SendFailure, encrypt, message_link, ready, send
from .targets import WORK_TARGETS, can_manage_work, can_read_work, is_assignee, record, record_label
from .work import WorkConflict, WorkInvalid, change_progress, save_work

User = get_user_model()
RULE_FLAGS = ('enabled', 'to_actor', 'to_subject', 'to_employee', 'to_manager')


def context(request, section='mail', **values):
    name = request.user.get_short_name() or request.user.get_username()
    return {'display_name': name, 'avatar_initial': name[:1], 'active_page': 'work' if section == 'work' else 'access_control',
            'access_tab': section, 'page_heading': 'متابعة الأعمال' if section == 'work' else 'إشعارات البريد', **values}


def page(request, template, status=200, section='mail', **values):
    return add_login_headers(render(request, 'makken_mail/' + template + '.html', context(request, section, **values), status=status))


def admin_audit(request, action, description):
    emit(actor=request.user, module='access_control', action=action, description=description, live=False)


@superuser_view
@require_GET
def index(request):
    query = request.GET.get('q', '').strip()[:100]
    category = request.GET.get('category', '')
    codes = [code for code, entry in CATALOG.items()
             if (not query or query.casefold() in (code + ' ' + entry.label).casefold()) and
             (not category or entry.category == category)]
    rules = EventRule.objects.filter(pk__in=codes).annotate(total=Count('recipients')).order_by('-enabled', 'code')
    paginated = Paginator(rules, resolve_page_size(request, 20)).get_page(request.GET.get('page'))
    for rule in paginated:
        rule.label = CATALOG[rule.code].label
    users = User.objects.order_by('first_name', 'last_name', User.USERNAME_FIELD).only('first_name', 'last_name', User.USERNAME_FIELD)
    params = request.GET.copy()
    params.pop('page', None)
    smtp = SMTPConfig.objects.filter(pk=1).first()
    req_tab = request.GET.get('tab', '')
    if req_tab in {'user', 'rules'}:
        active_tab = req_tab
    elif query or category or request.GET.get('page'):
        active_tab = 'rules'
    else:
        active_tab = 'user'
    if active_tab == 'rules':
        params['tab'] = 'rules'
    return page(request, 'rules', rules=paginated, users=users, q=query, category=category,
                categories=sorted(set(v.category for v in CATALOG.values())), configured=ready(smtp),
                sending_enabled=bool(smtp and smtp.enabled), paging=params.urlencode(), active_tab=active_tab)


@superuser_view
@require_http_methods(['GET', 'POST'])
def rule_editor(request, code):
    if code not in CATALOG:
        raise Http404
    rule = get_object_or_404(EventRule, pk=code)
    status = 200
    initial = {name: getattr(rule, name) for name in (*RULE_FLAGS, 'revision')}
    initial['recipients'] = list(rule.recipients.values_list('pk', flat=True))
    form = RuleForm(request.POST if request.method == 'POST' else None, rule=rule, initial=initial)
    if request.method == 'POST':
        if form.is_valid():
            with transaction.atomic():
                require_superuser(User.objects.get(pk=request.user.pk))
                locked = EventRule.objects.select_for_update().get(pk=code)
                if locked.revision != form.cleaned_data['revision']:
                    form.add_error(None, 'تغيّرت إعدادات النوع منذ فتحه. أعد تحميل الصفحة.')
                    status = 409
                else:
                    for key in RULE_FLAGS:
                        setattr(locked, key, form.cleaned_data.get(key, False))
                    locked.revision += 1
                    locked.save(update_fields=[*RULE_FLAGS, 'revision'])
                    locked.recipients.set(form.cleaned_data.get('recipients', ()))
                    admin_audit(request, 'update', 'تحديث قاعدة توجيه البريد')
                    messages.success(request, 'تم حفظ قاعدة البريد لهذا النوع.')
                    return redirect('makken_mail:index')
        else:
            status = 400
    return page(request, 'rule_editor', form=form, event_type=CATALOG[code], status=status)


def subscriptions(user):
    selected = sorted(code for code in user.makken_email_rules.values_list('pk', flat=True)
                      if code in CATALOG and not CATALOG[code].assignment_only)
    muted = sorted(set(user.makken_email_mutes.values_list('rule_id', flat=True)) & CATALOG.keys())
    fingerprint = hashlib.sha256(repr((selected, muted)).encode()).hexdigest()
    return {'selected': selected, 'muted': muted, 'fingerprint': fingerprint}


@superuser_view
@require_GET
def recipient_select(request):
    value = request.GET.get('person', '')
    if value.isascii() and value.isdigit() and len(value) < 19 and User.objects.filter(pk=int(value)).exists():
        return redirect('makken_mail:preferences', pk=int(value))
    messages.error(request, 'اختر مستخدمًا صالحًا أولًا.')
    return redirect('makken_mail:index')


@superuser_view
@require_http_methods(['GET', 'POST'])
def preferences(request, pk):
    user = get_object_or_404(User, pk=pk)
    status = 200
    form = UserPreferenceForm(request.POST if request.method == 'POST' else None, initial=subscriptions(user))
    if request.method == 'POST':
        if form.is_valid():
            with transaction.atomic():
                require_superuser(User.objects.get(pk=request.user.pk))
                list(EventRule.objects.select_for_update().order_by('pk').values_list('pk', flat=True))
                user = User.objects.select_for_update().get(pk=pk)
                if subscriptions(user)['fingerprint'] != form.cleaned_data['fingerprint']:
                    form.add_error(None, 'تغيّرت التفضيلات منذ فتح الصفحة. أعد تحميلها.')
                    status = 409
                else:
                    user.makken_email_rules.remove(*user.makken_email_rules.filter(pk__in=CATALOG))
                    user.makken_email_rules.add(*EventRule.objects.filter(pk__in=form.cleaned_data['selected']))
                    user.makken_email_mutes.filter(rule_id__in=CATALOG).delete()
                    RecipientMute.objects.bulk_create([RecipientMute(user=user, rule_id=k) for k in form.cleaned_data['muted']])
                    admin_audit(request, 'update', 'تحديث تفضيلات البريد لمستخدم')
                    messages.success(request, 'تم حفظ تفضيلات المستخدم.')
                    return redirect('makken_mail:index')
        else:
            status = 400
    return page(request, 'preferences', form=form, person=user, status=status)


@sensitive_post_parameters('password')
@sensitive_variables()
@superuser_view
@require_http_methods(['GET', 'POST'])
def smtp_settings(request):
    config = get_object_or_404(SMTPConfig, pk=1)
    initial = {name: getattr(config, name) for name in ('host', 'port', 'security', 'username', 'sender', 'sender_name', 'enabled', 'revision')}
    form = SMTPForm(request.POST if request.method == 'POST' else None, config=config, initial=initial)
    status = 200
    if request.method == 'POST':
        if form.is_valid():
            data = form.cleaned_data
            with transaction.atomic():
                require_superuser(User.objects.get(pk=request.user.pk))
                active = SMTPConfig.objects.select_for_update().get(pk=1)
                if active.revision != data['revision']:
                    form.add_error(None, 'تغيّرت إعدادات SMTP منذ فتحها. أعد تحميل الصفحة.')
                    status = 409
                else:
                    try:
                        if data['password']:
                            active.secret = encrypt(data['password'])
                        elif data['clear_password']:
                            active.secret = ''
                    except SendFailure as exc:
                        form.add_error(None, REASONS[exc.code])
                        status = 400
                    else:
                        for field in ('host', 'port', 'security', 'username', 'sender', 'sender_name', 'enabled'):
                            setattr(active, field, data[field])
                        active.revision += 1
                        active.save(update_fields=['host', 'port', 'security', 'username', 'sender', 'sender_name', 'enabled', 'secret', 'revision'])
                        admin_audit(request, 'update', 'تحديث إعدادات SMTP')
                        messages.success(request, 'تم حفظ إعدادات البريد.')
                        return redirect('makken_mail:smtp')
        else:
            status = 400
    return page(request, 'smtp', form=form, test_form=TestEmailForm(initial={'recipient': request.user.email}),
                configured=ready(config), has_password=bool(config.secret), status=status)


@superuser_view
@require_POST
def smtp_test(request):
    form = TestEmailForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'أدخل عنوان بريد صالحًا للتجربة.')
        return redirect('makken_mail:smtp')
    with transaction.atomic():
        require_superuser(User.objects.get(pk=request.user.pk))
        config = SMTPConfig.objects.select_for_update().get(pk=1)
        if not ready(config):
            messages.error(request, 'احفظ إعدادات SMTP الكاملة أولًا. لا يلزم تفعيل الإرسال العام للتجربة.')
            return redirect('makken_mail:smtp')
        now = timezone.now()
        if config.test_at and config.test_at > now - timedelta(seconds=60):
            messages.error(request, 'يمكن إرسال رسالة اختبار واحدة كل دقيقة. أعد المحاولة لاحقًا.')
            return redirect('makken_mail:smtp')
        config.test_at = now
        config.save(update_fields=['test_at'])
    sample = preview_values()
    try:
        send(config, form.cleaned_data['recipient'], sample, f'<makken-test-{uuid.uuid4().hex}@makken-notifications.invalid>')
    except SendFailure as exc:
        messages.error(request, REASONS.get(exc.code, REASONS['internal']))
        admin_audit(request, 'update', 'لم يتأكد إرسال اختبار SMTP' if exc.unknown else 'تعذّر اختبار SMTP')
    except Exception:
        messages.error(request, REASONS['internal'])
        admin_audit(request, 'update', 'تعذّر اختبار SMTP')
    else:
        messages.success(request, 'قبل مزود البريد رسالة الاختبار. تحقق من صندوق الوارد والبريد غير المرغوب فيه.')
        admin_audit(request, 'update', 'قبول مزود البريد رسالة اختبار SMTP')
    return redirect('makken_mail:smtp')


def preview_values():
    return {'title': 'رسالة اختبار البريد الإلكتروني', 'recipient_name': 'مستخدم مكّن',
            'description': 'هذه رسالة اختبار للتأكد من إعدادات البريد الإلكتروني في منصة مكّن.',
            'details': [('نوع الرسالة', 'اختبار الاتصال'), ('المنصة', 'مكّن')],
            'link': message_link(reverse('accounts:login'))}


@superuser_view
@require_GET
def preview(request):
    from django.templatetags.static import static
    response = add_login_headers(render(request, 'makken_mail/email.html', {
        **preview_values(), 'logo': static('makken_mail/logo-email.png')}))
    # This route serves a static sample. Permit only its inline email CSS,
    # with scripts, frames and outbound resources still disallowed.
    response['Content-Security-Policy'] = (
        "default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
    return response


@superuser_view
@require_GET
def deliveries(request):
    selected = request.GET.get('status', '')
    query = Delivery.objects.select_related('recipient', 'rule')
    if selected in DeliveryStatus.values:
        query = query.filter(status=selected)
    paginated = Paginator(query, resolve_page_size(request, 25)).get_page(request.GET.get('page'))
    for row in paginated:
        row.label = CATALOG[row.rule_id].label if row.rule_id in CATALOG else row.rule_id
        row.reason_label = REASONS.get(row.reason, '')
    return page(request, 'deliveries', rows=paginated, selected=selected, statuses=DeliveryStatus.choices,
                paging='status=' + selected if selected in DeliveryStatus.values else '')


@login_required(login_url='accounts:login')
def work_index(request):
    if request.method not in {'GET', 'HEAD'}:
        return denied(request)
    from access_control.policy import AccessPolicy
    policy = AccessPolicy(request.user)
    query = WorkAssignment.objects.select_related('employee', 'manager').prefetch_related('assignees')
    if not request.user.is_superuser:
        participates = Q(employee=request.user) | Q(assignees=request.user) | Q(manager=request.user)
        if policy.can('work_assignments', 'create') or policy.can('work_assignments', 'edit'):
            participates |= Q(created_by=request.user)
        query = query.filter(participates)
        # Check authoritative object scope without loading the full task list.
        from django.apps import apps
        from django.db.models import Subquery
        from access_control.regions import scoped
        from partnerships.models import Partnership
        visible = Q(target_model='') | Q(target_model='partnerships.partnership', employee=request.user) | Q(target_model='partnerships.partnership', assignees=request.user)
        for model, spec in WORK_TARGETS.items():
            if policy.can(spec.module):
                if model == 'agreement_clauses.agreement':
                    from agreement_clauses.models import Agreement
                    p_ids = scoped(Partnership._base_manager.all(), request.user).order_by().values('pk')
                    ids = Agreement._base_manager.filter(partnership_id__in=Subquery(p_ids)).order_by().values('pk')
                else:
                    ids = scoped(apps.get_model(model)._base_manager.all(), request.user).order_by().values('pk')
                visible |= Q(target_model=model, target_key__in=Subquery(ids))
        query = query.filter(visible).distinct()
    from .clause_sync import is_work_overdue, riyadh_today
    today = riyadh_today()
    status = request.GET.get('status', '')
    if status == 'overdue':
        query = query.filter(due_on__lt=today, status__in=(WorkStatus.NEW, WorkStatus.RUNNING))
    elif status in WorkStatus.values:
        query = query.filter(status=status)
    term = request.GET.get('q', '').strip()[:160]
    if term:
        query = query.filter(title__icontains=term)
    params = request.GET.copy()
    params.pop('page', None)
    can_create = request.user.is_superuser or policy.can('work_assignments', 'create')
    can_stats = request.user.is_superuser or policy.can('work_assignments', 'view')
    page_obj = Paginator(query, resolve_page_size(request, 20)).get_page(request.GET.get('page'))
    from partnerships.models import Partnership
    from agreement_clauses.models import Agreement
    p_ids = [r.target_key for r in page_obj if r.target_model == 'partnerships.partnership' and r.target_key]
    a_ids = [r.target_key for r in page_obj if r.target_model == 'agreement_clauses.agreement' and r.target_key]
    p_map = Partnership._base_manager.in_bulk(p_ids) if p_ids else {}
    a_map = {
        a.pk: a.partnership
        for a in Agreement._base_manager.select_related('partnership').filter(pk__in=a_ids)
    } if a_ids else {}
    for row in page_obj:
        linked = None
        if row.target_model == 'partnerships.partnership' and row.target_key:
            linked = p_map.get(row.target_key)
        elif row.target_model == 'agreement_clauses.agreement' and row.target_key:
            linked = a_map.get(row.target_key)
        row.linked_partnership = linked
        row.linked_partnership_url = (reverse('partnerships:edit', args=[linked.pk]) + '?from=my_work') if linked else ''
        row.is_overdue = is_work_overdue(row, today)
    status_choices = [*WorkStatus.choices, ('overdue', 'متأخرة')]
    return page(request, 'work_list', section='work', rows=page_obj,
                q=term, selected=status, statuses=status_choices, paging=params.urlencode(),
                can_create_work=can_create, can_view_stats=can_stats)


@module_view('work_assignments')
@require_GET
def work_stats(request):
    from access_control.policy import AccessPolicy
    from .stats import build_work_stats
    policy = AccessPolicy(request.user)
    stats = build_work_stats(request.user, request.GET)
    can_create = request.user.is_superuser or policy.can('work_assignments', 'create')
    return page(request, 'work_stats', section='work', active_page='work_stats', page_heading='إحصائيات المهام', stats=stats, can_create_work=can_create)


@module_view('work_assignments')
@require_http_methods(['GET', 'POST'])
def work_editor(request, pk=None):
    work = get_object_or_404(WorkAssignment.objects.prefetch_related('assignees'), pk=pk) if pk else None
    if work and not can_manage_work(request.user, work):
        return denied(request, 'لا تملك صلاحية تعديل أو إعادة إسناد هذا العمل.')
    assignee_ids = list(work.assignees.values_list('pk', flat=True)) if work else []
    if work and not assignee_ids and work.employee_id:
        assignee_ids = [work.employee_id]
    initial = ({key: getattr(work, key) for key in ('title', 'instructions', 'due_on', 'target_model', 'target_key', 'revision')}
               | {'employee': work.employee_id, 'assignees': assignee_ids, 'manager': work.manager_id}) if work else {}
    if not work and request.GET.get('model') in WORK_TARGETS:
        initial.update(target_model=request.GET['model'], target_key=request.GET.get('record', '')[:19])
    status = 200
    form = WorkForm(initial=initial, actor=request.user)
    if request.method == 'POST':
        try:
            work = save_work(request.user, request.POST, pk)
        except WorkInvalid as exc:
            form, status = exc.form, 400
        except WorkConflict as exc:
            form, status = WorkForm(request.POST, initial=initial, actor=request.user), 409
            form.add_error(None, str(exc))
        except PermissionDenied as exc:
            return denied(request, str(exc) or 'لا تملك صلاحية تنفيذ هذه العملية.')
        else:
            messages.success(request, 'تم حفظ إسناد العمل.')
            return redirect('makken_mail:work_detail', pk=work.pk)
    return page(request, 'work_editor', section='work', work=work, form=form, status=status)


@module_view('work_assignments')
@require_GET
def target_options(request):
    from django.apps import apps
    from access_control.policy import AccessPolicy
    from access_control.regions import scoped
    policy = AccessPolicy(request.user)
    if not (request.user.is_superuser or policy.can('work_assignments', 'create') or policy.can('work_assignments', 'edit')):
        return denied(request)
    model = request.GET.get('model')
    spec = WORK_TARGETS.get(model)
    if not spec or (not request.user.is_superuser and not policy.can(spec.module)):
        return add_login_headers(JsonResponse({'results': []}))
    if model == 'agreement_clauses.agreement':
        from agreement_clauses.models import Agreement
        from partnerships.models import Partnership
        visible_partners = scoped(Partnership._base_manager.all(), request.user)
        query = Agreement._base_manager.filter(partnership_id__in=visible_partners.values('pk')).select_related('partnership')
    else:
        query = scoped(apps.get_model(model)._base_manager.all(), request.user)
        if model in {'market_needs.sponsorship', 'market_needs.needexecution'}:
            query = query.select_related('need')
            if model == 'market_needs.sponsorship':
                query = query.select_related('partnership')
    term = request.GET.get('q', '').strip()[:100]
    if term:
        agr_num = term.upper().removeprefix('AGR-').lstrip('0') if model == 'agreement_clauses.agreement' and term.upper().startswith('AGR-') else ''
        if term.isascii() and term.isdigit() and len(term) < 19:
            query = query.filter(pk=int(term))
        elif agr_num and agr_num.isascii() and agr_num.isdigit():
            query = query.filter(pk=int(agr_num))
        elif model == 'agreement_clauses.agreement':
            query = query.filter(Q(title__icontains=term) | Q(partnership__name__icontains=term))
        else:
            field = {'market_needs.sponsorship': 'partnership__name', 'market_needs.needexecution': 'need__title',
                     'market_needs.need': 'title'}.get(model, 'name')
            query = query.filter(**{field + '__icontains': term})
    def _option_label(row):
        parts = [f'#{row.pk}', record_label(row)]
        dt = getattr(row, 'starts_on', None) or getattr(row, 'created_at', None) or getattr(row, 'updated_at', None)
        if dt:
            d = timezone.localtime(dt).date() if hasattr(dt, 'hour') else dt
            parts.append(d.strftime('%Y-%m-%d'))
        return ' · '.join(parts)

    return add_login_headers(JsonResponse({'results': [{'id': str(row.pk), 'label': _option_label(row)}
                                                      for row in query.order_by('-pk')[:40]]}))


@login_required(login_url='accounts:login')
@require_http_methods(['GET', 'POST'])
def work_detail(request, pk):
    work = get_object_or_404(WorkAssignment.objects.select_related('employee', 'manager').prefetch_related('assignees'), pk=pk)
    if not can_read_work(request.user, work):
        raise Http404
    open_work = work.status not in {WorkStatus.COMPLETE, WorkStatus.CANCELLED}
    allowed = (request.user.is_superuser or is_assignee(request.user, work)) and open_work
    can_reassign = can_manage_work(request.user, work) and open_work
    form, status = None, 200
    if allowed:
        form = ProgressForm(administrator=request.user.is_superuser, initial={
            'status': work.status, 'progress': work.progress, 'revision': work.revision})
    if request.method == 'POST':
        if not allowed:
            return denied(request, 'هذه العملية متاحة للموظف المسند إليه العمل ومدير النظام فقط.')
        try:
            change_progress(request.user, pk, request.POST)
        except WorkInvalid as exc:
            form, status = exc.form, 400
        except WorkConflict as exc:
            form, status = ProgressForm(request.POST, administrator=request.user.is_superuser), 409
            form.add_error(None, str(exc))
        except (WorkAssignment.DoesNotExist, PermissionDenied):
            raise Http404
        else:
            messages.success(request, 'تم حفظ متابعة العمل.')
            return redirect('makken_mail:work_detail', pk=pk)
    history = Paginator(work.history.select_related('actor'), resolve_page_size(request, 20)).get_page(request.GET.get('page'))
    for row in history:
        row.label = {'created': 'إسناد العمل', 'reassigned': 'تغيير الإسناد', 'progress': 'تحديث التقدم',
                     'edited': 'تعديل التفاصيل'}[row.action]
        row.status_label = dict(WorkStatus.choices).get(row.snapshot.get('status', ''), '')
    item = record(work.target_model, work.target_key)
    from .targets import record_path
    assignees = list(work.assignees.all()) or ([work.employee] if work.employee_id else [])
    return page(request, 'work_detail', section='work', work=work, assignees=assignees, can_reassign=can_reassign, form=form, status=status, history=history,
                linked=record_label(item), linked_url=record_path(item, WORK_TARGETS[work.target_model].module) if item else '')
