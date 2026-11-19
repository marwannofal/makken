from pathlib import Path
from uuid import uuid4


def evidence_path(instance, filename):
    return 'agreement-evidence/' + uuid4().hex + Path(filename).suffix.lower()
