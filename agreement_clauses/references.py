from django.contrib import messages
from django.core import signing
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from access_control.activity_capture import emit
from access_control.enforcement import module_view
from access_control.policy import for_request, require
from accounts.security import add_login_headers

from .models import AgreementOption, OptionKind
from .record_forms import OptionForm

SALT = 'makken.agreement-references.v1'
PERMISSIONS = {'add': 'create', 'edit': 'edit', 'toggle': 'change_status'}


def snapshot(user, kind, operation, item=None):
    return signing.dumps({
        'user': user.pk, 'kind': kind, 'operation': operation,
        'id': item.pk if item else None, 'revision': item.revision if item else None,
    }, salt=SALT)


def target_url(kind):
    return reverse('agreement_clauses:references') + '?kind=' + kind


@module_view('agreement_clauses')
@require_http_methods(['GET', 'POST'])
def reference_catalog(request):
    kind = request.GET.get('kind', OptionKind.ENTITY)
    if kind not in OptionKind.values:
        kind = OptionKind.ENTITY
    rows = AgreementOption.objects.filter(kind=kind)
    form, item, error, status = None, None, '', 200
    operation = ''
    if request.method == 'POST':
        try:
            raw = request.POST.get('snapshot', '')
            if not raw or len(raw) > 4096:
                raise signing.BadSignature
            data = signing.loads(raw, salt=SALT, max_age=20 * 60)
            operation = request.POST.get('operation')
            if (operation not in PERMISSIONS or data['user'] != request.user.pk or data['kind'] != kind
                    or data['operation'] != operation):
                raise signing.BadSignature
            require(request.user, 'agreement_clauses', PERMISSIONS[operation])
            with transaction.atomic():
                item = get_object_or_404(rows.select_for_update(), pk=data['id']) if data.get('id') else None
                if (operation == 'add') != (item is None):
                    raise signing.BadSignature
                if item and item.revision != data['revision']:
                    raise IntegrityError
                if operation == 'toggle':
                    item.is_active = not item.is_active
                    item.revision += 1
                    item.save(update_fields=['is_active', 'revision'])
                else:
                    form = OptionForm(request.POST, kind=kind, instance=item)
                    if not form.is_valid():
                        status = 400
                    else:
                        item = form.save(commit=False)
                        if item.pk:
                            item.revision += 1
                        item.save()
                if status == 200:
                    emit(actor=request.user, module='agreement_clauses', action={'add': 'create', 'edit': 'update', 'toggle': 'status'}[operation],
                         description='تحديث القوائم المرجعية للاتفاقيات', target_model='agreement_clauses.agreementoption',
                         target_key=str(item.pk), target_label=item.name, scope='global', live=False)
                    messages.success(request, 'تم حفظ الخيار.')
                    return add_login_headers(redirect(target_url(kind)))
        except (signing.BadSignature, KeyError):
            error, status = 'انتهت صلاحية الطلب. حدّث الصفحة ثم حاول مجددًا.', 400
        except IntegrityError:
            error, status = 'تغيّرت بيانات الخيار أو تكرر اسمه. حدّث الصفحة ثم حاول مجددًا.', 409
    elif edit := request.GET.get('edit'):
        operation = 'add' if edit == 'new' else 'edit'
        require(request.user, 'agreement_clauses', PERMISSIONS[operation])
        if operation == 'edit':
            item = get_object_or_404(rows, pk=int(edit)) if edit.isascii() and edit.isdigit() and len(edit) < 19 else None
        if item or operation == 'add':
            form = OptionForm(kind=kind, instance=item)

    policy = for_request(request)
    name = request.user.get_short_name() or request.user.get_username()
    context = {
        'page_heading': 'القوائم المرجعية للاتفاقيات', 'active_page': 'agreement_clauses',
        'display_name': name, 'avatar_initial': name[:1], 'kind': kind, 'kinds': OptionKind.choices,
        'rows': [(row, snapshot(request.user, kind, 'toggle', row)) for row in rows],
        'form': form, 'operation': operation, 'error': error, 'can_add': policy.can('agreement_clauses', 'create'),
        'can_edit': policy.can('agreement_clauses', 'edit'), 'can_toggle': policy.can('agreement_clauses', 'change_status'),
        'token': snapshot(request.user, kind, operation, item) if form is not None else '',
    }
    return add_login_headers(render(request, 'agreement_clauses/references.html', context, status=status))
