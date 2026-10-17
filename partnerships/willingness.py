"""Agreement validation, private file persistence and authenticated downloads."""
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
from .models import PreliminaryAgreementType, WillingnessAttachment

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


class WillingnessTransitionForm(forms.Form):
    agreement_type = forms.ChoiceField(label='نوع الاتفاق المبدئي', choices=[('', 'اختر نوع الاتفاق المبدئي'), *PreliminaryAgreementType.choices], error_messages={'required':'اختر نوع الاتفاق المبدئي.', 'invalid_choice':'اختر نوعًا صحيحًا من القائمة.'}, widget=forms.Select(attrs={'id':'willingness-agreement','required':True,'aria-describedby':'agreement-errors'}))
    attachments = MultipleAttachmentField(label='المرفقات الداعمة', widget=MultipleAttachmentInput(attrs={'id':'willingness-files','accept':'.pdf,.png,.jpg,.jpeg','required':True,'aria-describedby':'willingness-upload-help attachments-errors'}))


def save_supporting_files(item, cleaned, user, saved_paths):
    storage = willingness_storage()
    for upload in cleaned['attachments']:
        name = 'willingness/' + uuid.uuid4().hex + Path(upload.name).suffix.lower()
        saved_paths.append(name)  # Also clean a partially written file on errors.
        actual = storage.save(name, upload)
        if actual != name:
            saved_paths.append(actual)
        WillingnessAttachment.objects.create(partnership=item, file=actual, original_name=safe_filename(upload.name), size=upload.size, content_type=upload.verified_content_type, uploaded_by=user)
    item.preliminary_agreement_type = cleaned['agreement_type']


@login_required(login_url='accounts:login')
@require_GET
def download_attachment(request, pk, attachment_id):
    attachment = get_object_or_404(WillingnessAttachment, pk=attachment_id, partnership_id=pk)
    try:
        source = attachment.file.open('rb')
    except (OSError, ValueError):
        raise Http404
    response = FileResponse(source, as_attachment=True, filename=attachment.original_name, content_type=attachment.content_type)
    return add_login_headers(response)
