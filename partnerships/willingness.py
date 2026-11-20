"""Agreement validation, private file persistence and authenticated downloads."""
from access_control.enforcement import module_view
# MAKKEN RBAC INTEGRATION v1
import unicodedata
import uuid
import warnings
from pathlib import Path
from django import forms
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET
from PIL import Image
from pypdf import PdfReader
from accounts.security import add_login_headers
from .attachment_storage import willingness_storage
from .models import PartnershipType, PreliminaryAgreementType, WillingnessAttachment

MAX_FILE_SIZE = 100 * 1024 * 1024
MAX_FILES = 20
ACCEPTED_TYPES = {'.pdf':'application/pdf', '.png':'image/png', '.jpg':'image/jpeg', '.jpeg':'image/jpeg'}


def safe_filename(name):
    name = str(name).replace('\\', '/').rsplit('/', 1)[-1]
    name = ''.join(c for c in unicodedata.normalize('NFKC', name) if not unicodedata.category(c).startswith('C'))
    suffix = Path(name).suffix.lower()
    return (Path(name).stem[:190] or 'attachment') + suffix


def validate_attachment(upload):
    if not upload or not getattr(upload, 'size', 0):
        raise forms.ValidationError('لا يمكن رفع ملف فارغ.')
    if upload.size > MAX_FILE_SIZE:
        raise forms.ValidationError('الحد الأقصى لكل مرفق هو 100 MB.')
    suffix = Path(upload.name).suffix.lower()
    if suffix not in ACCEPTED_TYPES:
        raise forms.ValidationError('الملفات المسموحة هي PDF وPNG وJPG وJPEG فقط.')
    try:
        upload.seek(0)
        if suffix == '.pdf':
            if upload.read(5) != b'%PDF-':
                raise ValueError('Invalid PDF header')
            upload.seek(0)
            reader = PdfReader(upload, strict=True)
            if reader.is_encrypted or len(reader.pages) < 1:
                raise ValueError('Encrypted or empty PDF')
        else:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                image = Image.open(upload)
                if image.format != ('PNG' if suffix == '.png' else 'JPEG'):
                    raise ValueError('Extension/content mismatch')
                image.verify()
    except Exception as exc:
        # File parsers have format-specific exception classes; none should escape
        # as a server error for an invalid user document.
        raise forms.ValidationError('الملف تالف أو لا يطابق امتداده، أو ملف PDF محمي بكلمة مرور.') from exc
    finally:
        upload.seek(0)
    upload.verified_content_type = ACCEPTED_TYPES[suffix]
    return upload


class MultipleAttachmentInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleAttachmentField(forms.FileField):
    widget = MultipleAttachmentInput

    def clean(self, data, initial=None):
        files = data if isinstance(data, (list, tuple)) else [data] if data else []
        if not files:
            raise forms.ValidationError('أضف مرفقًا داعمًا واحدًا على الأقل.')
        if len(files) > MAX_FILES:
            raise forms.ValidationError('يمكن رفع 20 مرفقًا كحد أقصى في التحويل الواحد.')
        clean_one = super().clean
        errors, cleaned = [], []
        for file in files:
            try:
                cleaned.append(validate_attachment(clean_one(file, initial)))
            except forms.ValidationError as exc:
                errors.extend(forms.ValidationError('%(name)s: %(error)s', params={'name': safe_filename(getattr(file,'name','مرفق')), 'error': message}) for message in exc.messages)
        if errors:
            raise forms.ValidationError(errors)
        return cleaned


LEGACY_TYPE_BY_NAME = {
    'مذكرة تفاهم': PreliminaryAgreementType.MOU,
    'تعاون': PreliminaryAgreementType.COOPERATION,
    'عقد خدمة': PreliminaryAgreementType.SERVICE_CONTRACT,
    'اجتماعية': PreliminaryAgreementType.SOCIAL,
}
LEGACY_NAME_BY_CODE = {v: k for k, v in LEGACY_TYPE_BY_NAME.items()}


class PartnershipTypeField(forms.ModelChoiceField):
    def to_python(self, value):
        if isinstance(value, str) and value in LEGACY_NAME_BY_CODE:
            obj = self.queryset.filter(name=LEGACY_NAME_BY_CODE[value]).first()
            if obj is not None:
                return obj
        return super().to_python(value)


class WillingnessTransitionForm(forms.Form):
    agreement_type = PartnershipTypeField(
        label='نوع الشراكة',
        queryset=PartnershipType.objects.none(),
        empty_label='اختر نوع الشراكة',
        error_messages={'required': 'اختر نوع الشراكة.', 'invalid_choice': 'اختر نوعًا صحيحًا من القائمة.'},
        widget=forms.Select(attrs={'id': 'willingness-agreement', 'required': True, 'aria-describedby': 'agreement-errors'}),
    )
    attachments = MultipleAttachmentField(label='المرفقات الداعمة', widget=MultipleAttachmentInput(attrs={'id': 'willingness-files', 'accept': '.pdf,.png,.jpg,.jpeg', 'required': True, 'aria-describedby': 'willingness-upload-help attachments-errors'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['agreement_type'].queryset = PartnershipType.objects.filter(is_active=True).order_by('id')


def save_supporting_files(item, cleaned, user, saved_paths):
    storage = willingness_storage()
    for upload in cleaned['attachments']:
        name = 'willingness/' + uuid.uuid4().hex + Path(upload.name).suffix.lower()
        saved_paths.append(name)  # Also clean a partially written file on errors.
        actual = storage.save(name, upload)
        if actual != name:
            saved_paths.append(actual)
        WillingnessAttachment.objects.create(partnership=item, file=actual, original_name=safe_filename(upload.name), size=upload.size, content_type=upload.verified_content_type, uploaded_by=user)
    selected_type = cleaned['agreement_type']
    if isinstance(selected_type, PartnershipType):
        item.partnership_type = selected_type
        item.preliminary_agreement_type = LEGACY_TYPE_BY_NAME.get(selected_type.name, PreliminaryAgreementType.OTHER)
    else:
        item.preliminary_agreement_type = selected_type if selected_type in PreliminaryAgreementType.values else PreliminaryAgreementType.OTHER


@module_view('partnerships')
@login_required(login_url='accounts:login')
@require_GET
def download_attachment(request, pk, attachment_id):
    from access_control.regions import scoped
    from .models import Partnership
    attachment = get_object_or_404(WillingnessAttachment.objects.filter(partnership_id__in=scoped(Partnership.objects.all(), request.user).values('pk')), pk=attachment_id, partnership_id=pk)
    try:
        source = attachment.file.open('rb')
    except (OSError, ValueError):
        raise Http404
    request._activity_target = attachment.partnership
    response = FileResponse(source, as_attachment=True, filename=attachment.original_name, content_type=attachment.content_type)
    return add_login_headers(response)
