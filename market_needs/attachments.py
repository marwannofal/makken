"""Reuse the project's private store; support evidence has a separate namespace."""
import warnings
from pathlib import Path
from django import forms
from django.conf import settings
from PIL import Image
from pypdf import PdfReader
from partnerships.willingness import ACCEPTED_TYPES, safe_filename


def validate_support_attachment(upload):
    limit = getattr(settings, "MAKKEN_SUPPORT_MAX_FILE_SIZE", 100 * 1024 * 1024)
    suffix = Path(upload.name).suffix.lower()
    if not upload.size or upload.size > limit:
        raise forms.ValidationError(f"حجم المرفق يجب أن يكون أكبر من صفر وبحد أقصى {limit // (1024 * 1024)} MiB.")
    if suffix not in ACCEPTED_TYPES:
        raise forms.ValidationError("المسموح PDF وPNG وJPG وJPEG فقط.")
    try:
        upload.seek(0)
        if suffix == ".pdf":
            if upload.read(5) != b"%PDF-":
                raise ValueError
            upload.seek(0)
            pdf = PdfReader(upload, strict=True)
            if pdf.is_encrypted or not len(pdf.pages):
                raise ValueError
        else:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                image = Image.open(upload)
                if image.format != ("PNG" if suffix == ".png" else "JPEG"):
                    raise ValueError
                image.verify()
    except Exception as exc:
        raise forms.ValidationError("الملف تالف أو لا يطابق امتداده، أو ملف PDF محمي بكلمة مرور.") from exc
    finally:
        upload.seek(0)
    upload.verified_content_type = ACCEPTED_TYPES[suffix]
    return upload
