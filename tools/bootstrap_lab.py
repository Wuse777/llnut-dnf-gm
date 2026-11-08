"""Download pinned official runtime files into a local directory; never uses sudo."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import urllib.request


def checksum(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def download(entry, runtime):
    path = runtime / entry['path']
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if checksum(path) != entry['sha256']:
            raise SystemExit('Runtime checksum mismatch: ' + entry['path'])
        return
    tmp = path.with_suffix(path.suffix + '.part')
    try:
        with urllib.request.urlopen(entry['url'], timeout=60) as src, tmp.open('wb') as dst:
            shutil.copyfileobj(src, dst, 1024 * 1024)
        if checksum(tmp) != entry['sha256']:
            raise SystemExit('Runtime checksum mismatch: ' + entry['path'])
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', required=True)
    args = parser.parse_args()
    runtime = Path(args.runtime).resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    for entry in json.loads((root / 'tools/runtime-sources.json').read_text(encoding='utf-8')):
        download(entry, runtime)
    mysql = runtime / 'mysql'
    mysql.mkdir(exist_ok=True)
    wanted = {'bin/mysql', 'bin/mysqld', 'bin/mysqldump', 'share/english/errmsg.sys'}
    with tarfile.open(runtime / 'downloads/mysql-5.7.44.tar.gz') as archive:
        for member in archive:
            name = member.name.split('/', 1)[-1]
            if name not in wanted:
                continue
            member.name = name
            archive.extract(member, mysql, filter='data')
    for name in ['libaio', 'libncurses5', 'libtinfo5']:
        subprocess.run(['dpkg-deb', '-x', str(runtime / 'downloads' / f'{name}.deb'), str(mysql / 'deps')], check=True)
    venv = runtime / 'venv'
    # Bundled ensurepip seeds only this venv; no mutable pip.pyz download.
    subprocess.run([sys.executable, '-m', 'venv', str(venv)], check=True)
    env = os.environ.copy()
    env.pop('PYTHONPATH', None)
    subprocess.run([str(venv / 'bin/python'), '-m', 'pip', 'install', '--disable-pip-version-check', '-r', str(root / 'requirements.lock')], env=env, check=True)
    print(json.dumps({'status': 'ready', 'runtime': str(runtime), 'global_packages_changed': False}))


if __name__ == '__main__':
    main()
