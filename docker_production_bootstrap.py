import os
import subprocess
import sys

subprocess.run(
    [sys.executable, "manage.py", "migrate", "--noinput"],
    check=True,
)
subprocess.run(
    [sys.executable, "manage.py", "collectstatic", "--noinput"],
    check=True,
)

subprocess.run(
    [sys.executable, "manage.py", "build_error_pages"],
    check=True,
)

os.execvp(sys.argv[1], sys.argv[1:])
