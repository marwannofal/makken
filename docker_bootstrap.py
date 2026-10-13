from pathlib import Path
import os
import sqlite3
import subprocess
import sys

source = Path("/app/db.sqlite3")
target = Path("/data/db.sqlite3")

if source.exists() and not target.exists():
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as old:
        with sqlite3.connect(target) as new:
            old.backup(new)
    print("Existing database imported into Docker.")

subprocess.run(
    [sys.executable, "manage.py", "migrate", "--noinput"],
    check=True,
)

os.execvp(sys.argv[1], sys.argv[1:])
