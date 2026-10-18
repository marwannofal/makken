#!/usr/bin/env python3
"""Run the new suite on a disposable, separately named MySQL Docker stack."""
import argparse
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', default='/var/www/html/makken')
    args = parser.parse_args()
    project = Path(args.project).resolve()
    config = project/'compose.market-tests.yaml'
    if not config.is_file() or not (project/'Dockerfile.production').is_file():
        sys.exit('Install the update in the Docker production project first.')
    command = ['docker', 'compose', '--project-name', 'makken-market-tests', '-f', str(config)]
    result = 1
    try:
        result = subprocess.run([*command, 'up', '--build', '--abort-on-container-exit', '--exit-code-from', 'tests'], cwd=project).returncode
    finally:
        # Only the isolated test namespace is removed, including on test failure.
        subprocess.run([*command, 'down', '--volumes', '--remove-orphans'], cwd=project)
    sys.exit(result)


if __name__ == '__main__':
    main()
