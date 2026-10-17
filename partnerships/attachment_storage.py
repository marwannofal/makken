"""Private files: deliberately separate from public MEDIA_ROOT."""
import logging
import os
import uuid
from pathlib import Path
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible


@deconstructible
class PrivateAttachmentStorage(FileSystemStorage):
    def __init__(self):
        super().__init__(file_permissions_mode=0o600, directory_permissions_mode=0o700)

    @property
    def base_location(self):
        return Path(getattr(settings, 'MAKKEN_PRIVATE_UPLOAD_ROOT', Path(settings.BASE_DIR) / 'private_uploads'))

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    def url(self, name):
        raise ValueError('Private attachments are available only through the authenticated download view.')


def willingness_storage():
    return PrivateAttachmentStorage()


def attachment_path(instance, filename):
    return 'willingness/' + uuid.uuid4().hex + Path(filename).suffix.lower()


def delete_private_files(paths):
    storage = willingness_storage()
    for name in paths:
        try:
            storage.delete(name)
        except OSError:
            logging.getLogger(__name__).exception('Could not delete a private attachment')
