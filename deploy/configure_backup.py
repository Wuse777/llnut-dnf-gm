#!/usr/bin/env python3
"""Installer-only private online backup wiring, never a game/service command."""
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from dnfgm.config import Settings
from dnfgm.db import Database
from dnfgm.alerts import atomic
from dnfgm.inventory_fence import directory
from dnfgm.release_files import read_json
from configure_task_probe import read_private,replace_private
from inventory_probe import validate
from backup_worker import configuration,private_directory,ROOT,CONFIG


def main():
    if os.geteuid()!=0:raise SystemExit('Root-only installer configuration')
    app=Path('/etc/dnf-gm/config.json');directory(app.parent,0)
    original=read_private(app,(0,),0o027)
    settings=Settings(**original[0]).check()
    # The existing reviewed Docker identity authorizes credential provisioning.
    # No secret in argv, stdout, application config, release, report or API.
    policy=Path('/etc/dnf-gm/inventory-maintenance.json')
    if not policy.exists():print('Automatic backup not configured: reviewed worker policy missing.');return
    cfg=validate(read_json(policy,owner=0,limit=65536))
    with Database(settings).connect() as c,c.cursor() as q:
        q.execute('SELECT version FROM dnf_gm.schema_versions WHERE version=16')
        if not q.fetchone():raise ValueError('Backup migration missing')
    ROOT.parent.mkdir(mode=0o700,exist_ok=True)
    directory(ROOT.parent,0)
    if not ROOT.exists():ROOT.mkdir(mode=0o700)
    private_directory(ROOT)
    if not CONFIG.exists():
        result=subprocess.run(['docker','exec',cfg['container'],'printenv','DNF_DB_ROOT_PASSWORD'],capture_output=True,timeout=15,check=True)
        password=result.stdout.decode().strip()
        if not password:raise ValueError('Missing maintenance credential')
        fd=os.open(CONFIG,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as f:
            json.dump({'version':1,'host':settings.db_host,'port':settings.db_port,'user':'root','password':password},f);f.flush();os.fsync(f.fileno())
    configuration(CONFIG,settings)
    # Give the root worker a fixed writable DIRECTORY for atomic report rename;
    # a file-only systemd bind mount would prevent atomic replacement.
    evidence=Path('/var/lib/dnf-gm/backup-evidence/health.json')
    if settings.backup_health_file not in ('/var/lib/dnf-gm/backup-health.json',str(evidence)):
        raise ValueError('Unsupported evidence path')
    evidence.parent.mkdir(mode=0o755,exist_ok=True);directory(evidence.parent,0)
    if not evidence.exists():
        prior=Path('/var/lib/dnf-gm/backup-health.json')
        report=read_json(prior,owner=0,limit=65536) if prior.exists() else {'version':1,'scope':'management_only','checked_at':0,'integrity':'unavailable'}
        atomic(evidence,report,mode=0o644)
    if settings.backup_health_file!=str(evidence):
        updated={**original[0],'backup_health_file':str(evidence)}
        Settings(**updated).check();replace_private(app,updated,original,(0,),0o027)
    print('Private management-backup source configured; no game rows or service commands.')

if __name__=='__main__':
    try:main()
    except Exception:raise SystemExit('Backup setup refused; credential/SQL details suppressed.') from None
