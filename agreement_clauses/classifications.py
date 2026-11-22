"""Standalone RBAC & dependency-protected lookup view for تصنيف الاتفاقية."""
from urllib.parse import urlencode

from django import forms
from django.contrib import messages
from django.core import signing
from django.core.paginator import Paginator
from core.pagination import resolve_page_size
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from access_control.activity_capture import emit
from access_control.enforcement import module_view
from access_control.policy import for_request, require
from accounts.security import add_login_headers
from core.dependencies import DependencyBlocked, blocked_context, ensure_allowed

from .models import AgreementClassification, normalize_name, validate_name

SALT = 'makken.agreement-classifications.v1'
PERMISSIONS = {'add': 'create', 'edit': 'edit', 'toggle': 'change_status', 'delete': 'delete'}


class ClassificationForm(forms.ModelForm):
    class Meta:
        model = AgreementClassification
        fields = ['name']
        widgets = {
            'name': forms.TextInput(attrs={'maxlength': '200', 'placeholder': 'أدخل اسم تصنيف الاتفاقية', 'autofocus': True}),
        }

    def clean_name(self):
        value = normalize_name(self.cleaned_data.get('name', ''))
        validate_name(value)
        if not value:
            raise forms.ValidationError('أدخل اسم تصنيف الاتفاقية.')
        qs = AgreementClassification.objects.filter(name_key=value.casefold())
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('يوجد تصنيف بهذا الاسم بالفعل.')
        return value


def _snapshot(user, operation, item=None):
    return signing.dumps({
        'user': user.pk,
        'operation': operation,
        'id': item.pk if item else None,
        'revision': item.revision if item else None,
    }, salt=SALT)


@module_view('agreement_classifications')
@require_http_methods(['GET', 'POST'])
def classifications_index(request):
    base_rows = AgreementClassification.objects.all()
    form, item, error, status = None, None, '', 200
    extra_context = {}
    operation = ''

    if request.method == 'POST':
        try:
            raw = request.POST.get('snapshot', '')
            if not raw or len(raw) > 4096:
                raise signing.BadSignature
            data = signing.loads(raw, salt=SALT, max_age=20 * 60)
            operation = request.POST.get('operation')
            if (operation not in PERMISSIONS or data['user'] != request.user.pk
                    or data['operation'] != operation):
                raise signing.BadSignature
            require(request.user, 'agreement_classifications', PERMISSIONS[operation])
            with transaction.atomic():
                item = get_object_or_404(base_rows.select_for_update(), pk=data['id']) if data.get('id') else None
                if (operation == 'add') != (item is None):
                    raise signing.BadSignature
                if item and item.revision != data['revision']:
                    raise IntegrityError
                if operation == 'delete':
                    ensure_allowed(item, 'delete')
                    deleted_pk, deleted_name = str(item.pk), item.name
                    item.delete()
                    emit(actor=request.user, module='agreement_classifications', action='delete',
                         description='حذف تصنيف اتفاقية', target_model='agreement_clauses.agreementclassification',
                         target_key=deleted_pk, target_label=deleted_name, scope='global', live=False)
                    messages.success(request, f'تم حذف تصنيف الاتفاقية «{deleted_name}».')
                    return add_login_headers(redirect('agreement_clauses:classifications'))
                if operation == 'toggle':
                    new_active = not item.is_active
                    ensure_allowed(item, 'toggle', active=new_active)
                    item.is_active = new_active
                    item.revision += 1
                    item.save(update_fields=['is_active', 'revision', 'updated_at'])
                else:
                    form = ClassificationForm(request.POST, instance=item)
                    if not form.is_valid():
                        status = 400
                    else:
                        item = form.save(commit=False)
                        if item.pk:
                            item.revision += 1
                        item.save()
                if status == 200:
                    emit(actor=request.user, module='agreement_classifications',
                         action={'add': 'create', 'edit': 'update', 'toggle': 'status'}[operation],
                         description='تحديث تصنيف الاتفاقية', target_model='agreement_clauses.agreementclassification',
                         target_key=str(item.pk), target_label=item.name, scope='global', live=False)
                    messages.success(request, 'تم حفظ تصنيف الاتفاقية.')
                    return add_login_headers(redirect('agreement_clauses:classifications'))
        except DependencyBlocked as exc:
            extra_context.update(blocked_context(exc))
            error, status = str(exc), 409
        except ProtectedError:
            error, status = 'لا يمكن حذف تصنيف الاتفاقية لارتباطه بسجلات أخرى.', 409
        except (signing.BadSignature, KeyError):
            error, status = 'انتهت صلاحية الطلب. حدّث الصفحة ثم حاول مجددًا.', 400
        except IntegrityError:
            error, status = 'تغيّرت بيانات التصنيف أو تكرر اسمه. حدّث الصفحة ثم حاول مجددًا.', 409
    elif edit := request.GET.get('edit'):
        operation = 'add' if edit == 'new' else 'edit'
        require(request.user, 'agreement_classifications', PERMISSIONS[operation])
        if operation == 'edit':
            item = get_object_or_404(base_rows, pk=int(edit)) if edit.isascii() and edit.isdigit() and len(edit) < 19 else None
        if item or operation == 'add':
            form = ClassificationForm(instance=item)

    q = (request.GET.get('q') or '').strip()[:200]
    status_filter = request.GET.get('status', '')
    if status_filter not in {'1', '0'}:
        status_filter = ''
    filtered = base_rows
    if q:
        filtered = filtered.filter(name__icontains=q)
    if status_filter == '1':
        filtered = filtered.filter(is_active=True)
    elif status_filter == '0':
        filtered = filtered.filter(is_active=False)

    page_obj = Paginator(filtered, resolve_page_size(request, 20)).get_page(request.GET.get('page'))
    filter_params = {}
    if q:
        filter_params['q'] = q
    if status_filter:
        filter_params['status'] = status_filter
    filter_query = urlencode(filter_params)

    policy = for_request(request)
    name = request.user.get_short_name() or request.user.get_username()
    row_items = [
        {
            'item': row,
            'toggle_snapshot': _snapshot(request.user, 'toggle', row),
            'delete_snapshot': _snapshot(request.user, 'delete', row),
        }
        for row in page_obj
    ]
    context = {
        'page_heading': 'تصنيف الاتفاقية',
        'active_page': 'agreement_classifications',
        'display_name': name,
        'avatar_initial': name[:1],
        'row_items': row_items,
        'page_obj': page_obj,
        'settings_filter_q': q,
        'settings_filter_status': status_filter,
        'settings_filter_active': bool(q or status_filter),
        'settings_filter_query': filter_query,
        'form': form,
        'operation': operation,
        'error': error,
        'can_add': policy.can('agreement_classifications', 'create'),
        'can_edit': policy.can('agreement_classifications', 'edit'),
        'can_toggle': policy.can('agreement_classifications', 'change_status'),
        'can_delete': policy.can('agreement_classifications', 'delete'),
        'token': _snapshot(request.user, operation, item) if form is not None else '',
        **extra_context,
    }
    return add_login_headers(render(request, 'agreement_clauses/classifications.html', context, status=status))
