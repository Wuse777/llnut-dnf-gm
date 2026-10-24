"""Root-only bootstrap for a NEW installation. Never prints credentials.

Uses the existing container's DNF_DB_ROOT_PASSWORD environment internally. No
password in argv or repository; no game rows or game table structures changed.
DDL is not transactional: on failure inspect locally; do not blindly rerun.
"""
import argparse
from getpass import getpass
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from dnfgm.config import Settings
from dnfgm.security import PASSWORDS
from grants import bootstrap_sql


def mysql(container, port, sql):
    # The fixed shell expands only the container's preexisting secret.
    result = subprocess.run(['docker', 'exec', '-i', container, 'sh', '-c',
        'test -n "$DNF_DB_ROOT_PASSWORD" && MYSQL_PWD="$DNF_DB_ROOT_PASSWORD" exec mysql --protocol=TCP -h127.0.0.1 -P"$1" -uroot --default-character-set=utf8mb4 --batch --skip-column-names',
        'dnf-gm-provision', str(port)], input=sql.encode(), capture_output=True, timeout=60)
    if result.returncode:
        raise RuntimeError('Database maintenance command failed; SQL/credentials suppressed')
    return result.stdout.decode().strip()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', required=True, help='Reviewed example configuration; generated secrets replace placeholders')
    p.add_argument('--container', required=True)
    p.add_argument('--mysql-port', type=int, default=4000)
    p.add_argument('--db-account-host', required=True, help='Exact source address as seen by MySQL, no wildcards')
    a = p.parse_args()
    if os.geteuid() != 0:
        raise SystemExit('Root required')
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}', a.container) or not 1 <= a.mysql_port <= 65535:
        raise SystemExit('Invalid container or port')
    home = Path('/etc/dnf-gm')
    path = home / 'config.json'
    if path.exists():
        raise SystemExit('Refuse to overwrite existing configuration; upgrades do not reprovision')
    cfg = json.loads(Path(a.config).read_text())
    if cfg.get('writes') or cfg.get('public') or cfg.get('require_totp'):
        raise SystemExit('Bootstrap is tunnel-only, password-only and read-only; activate separately')
    cfg.update(db_password=secrets.token_hex(32), secret=secrets.token_hex(32))
    Settings(**cfg).check()
    password = getpass('New admin password (at least 20 characters): ')
    if len(password) < 20 or password != getpass('Repeat admin password: '):
        raise SystemExit('Password too short or mismatch')
    sql = bootstrap_sql({**cfg, 'db_account_host': a.db_account_host}, PASSWORDS.hash(password))
    if mysql(a.container, a.mysql_port, "SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME='dnf_gm';") != '0':
        raise SystemExit('Existing management database: refuse bootstrap')
    try:
        owner = pwd.getpwnam('dnfgm')
    except KeyError:
        subprocess.run(['useradd', '--system', '--no-create-home', '--shell', '/usr/sbin/nologin', 'dnfgm'], check=True)
        owner = pwd.getpwnam('dnfgm')
    home.mkdir(mode=0o750, exist_ok=True)
    os.chown(home, 0, owner.pw_gid)
    os.chmod(home, 0o750)
    # Reserve private config first: a partial bootstrap cannot silently reset credentials.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(cfg, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.chown(path, owner.pw_uid, owner.pw_gid)
    mysql(a.container, a.mysql_port, sql)
    print('Created dedicated grants and admin. Username: admin. Secrets remain only in private config.')


if __name__ == '__main__':
    main()
