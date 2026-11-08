#!/usr/bin/env python3
"""Private GM management backup and isolated recovery proof, not game rollback."""
import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import pymysql
from dnfgm.backup import dump,restore_drill,assert_lab,canonical
from dnfgm.backup_health import verify_evidence,private_receipt
from dnfgm.alerts import atomic


def write_new(path,value):
    path=Path(path)
    if not path.is_absolute():raise ValueError('Absolute private receipt path required')
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as f:f.write(canonical(value)+b'\n');f.flush();os.fsync(f.fileno())


def stopped_gm():
    r=subprocess.run(['systemctl','show','dnf-gm.service','--property=LoadState,ActiveState,MainPID'],capture_output=True,text=True,timeout=5,check=True)
    d=dict(x.split('=',1) for x in r.stdout.splitlines() if '=' in x)
    if d.get('LoadState')!='loaded' or d.get('ActiveState')!='inactive' or d.get('MainPID')!='0':
        raise ValueError('GM must already be stopped by the operator')
    if not Path('/var/lib/dnf-gm/no-auto-recover').is_file():raise ValueError('Explicit recovery inhibition required during maintenance')


@contextmanager
def source(args):
    if args.lab_socket:
        if not args.lab_datadir:raise ValueError('Explicit lab datadir required')
        c=pymysql.connect(unix_socket=args.lab_socket,user='root',charset='utf8mb4',autocommit=False,read_timeout=10,write_timeout=10,local_infile=False)
        try:assert_lab(c,args.lab_socket,args.lab_datadir);yield c
        finally:c.close()
    else:
        if os.geteuid()!=0 or not args.connection_file:raise ValueError('Root-owned production maintenance context required')
        if '/dnf-gm.slice/' not in Path('/proc/self/cgroup').read_text():raise ValueError('Run production maintenance inside the existing GM resource slice')
        if Path(args.connection_file).lstat().st_uid!=0:raise ValueError('Root-owned connection file required')
        cfg=private_receipt(args.connection_file)
        if set(cfg)!={'host','port','user','password'} or cfg['user']!='root':raise ValueError('Explicit private maintenance connection required')
        # Schema feature visibility must be complete. These credentials never go
        # to the app or backup receipt; there is no new runtime permission.
        with open('/var/lib/dnf-gm/maintenance.lock','a') as lock:
            os.chmod(lock.name,0o600);fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            stopped_gm()
            c=pymysql.connect(host=cfg['host'],port=cfg['port'],user=cfg['user'],password=cfg['password'],charset='utf8mb4',autocommit=False,connect_timeout=3,read_timeout=10,write_timeout=10,local_infile=False)
            try:yield c;stopped_gm()
            finally:c.close()


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    b=sub.add_parser('backup');b.add_argument('--output',required=True);b.add_argument('--receipt',required=True)
    b.add_argument('--lab-socket');b.add_argument('--lab-datadir');b.add_argument('--connection-file')
    r=sub.add_parser('restore-check');r.add_argument('--artifact',required=True);r.add_argument('--sha256',required=True);r.add_argument('--lab-socket',required=True);r.add_argument('--lab-datadir',required=True);r.add_argument('--receipt',required=True)
    d=sub.add_parser('rehearse-latest');d.add_argument('--backup-root',required=True);d.add_argument('--lab-socket',required=True);d.add_argument('--lab-datadir',required=True);d.add_argument('--receipt',required=True);d.add_argument('--health-output',required=True)
    h=sub.add_parser('publish-health');h.add_argument('--artifact',required=True);h.add_argument('--backup-receipt',required=True);h.add_argument('--restore-receipt');h.add_argument('--output',required=True)
    args=p.parse_args()
    if args.command!='publish-health' and (Path(args.receipt).exists() or Path(args.receipt).is_symlink()):raise FileExistsError('Receipt already exists')
    if args.command=='backup':
        if bool(args.lab_socket)==bool(args.connection_file):raise ValueError('Choose exactly one source')
        with source(args) as c:receipt=dump(c,args.output)
        write_new(args.receipt,receipt)
        print(json.dumps({k:receipt[k] for k in ('state','scope','artifact_sha256','tables','rows')}))
    elif args.command=='restore-check':
        receipt=restore_drill(args.artifact,args.sha256,socket=args.lab_socket,datadir=args.lab_datadir)
        write_new(args.receipt,receipt);print(json.dumps({k:receipt[k] for k in ('state','scope','tables','rows')}))
    elif args.command=='rehearse-latest':
        from dnfgm.backup_rehearsal import rehearse_latest
        output=Path(args.health_output)
        if (not output.is_absolute() or os.path.lexists(output)
                or output.resolve().is_relative_to(Path(args.backup_root).resolve())
                or output.resolve()==Path(args.receipt).resolve()):
            raise ValueError('New health output outside backup retention required')
        report=rehearse_latest(args.backup_root,args.receipt,socket=args.lab_socket,datadir=args.lab_datadir)
        # No replace of an old report or of private evidence during rehearsal.
        fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o644)
        with os.fdopen(fd,'wb') as f:f.write(canonical(report)+b'\n');f.flush();os.fsync(f.fileno())
        print(json.dumps({'state':'verified','scope':'management_only','restore':'verified',
            **{key:report['backup'][key] for key in ('artifact_sha256','bytes','tables','rows')}}))
    else:
        output=Path(args.output)
        if not output.is_absolute():raise ValueError('Absolute public report path required')
        sources=[Path(x) for x in (args.artifact,args.backup_receipt,args.restore_receipt) if x]
        if output.is_symlink() or any(output.resolve()==x.resolve() or (output.exists() and x.exists() and output.samefile(x)) for x in sources):
            raise ValueError('Health report cannot replace backup evidence')
        if output.exists():
            from dnfgm.alerts import read_json
            previous=read_json(output)
            if previous.get('version')!=1 or previous.get('scope')!='management_only' or 'integrity' not in previous or 'backup' not in previous or 'restore' not in previous:
                raise ValueError('Will not replace an unrelated file')
        # Explicit selected maintenance destination only; never copies content.
        report=verify_evidence(args.artifact,args.backup_receipt,args.restore_receipt)
        atomic(output,report,0o644)
        print(json.dumps({'state':report['integrity'],'scope':'management_only','restore':(report['restore'] or {}).get('state','not_recorded')}))
        if report['integrity']!='verified':raise SystemExit(1)


if __name__=='__main__':
    try:main()
    except Exception:
        print('Backup or restore check did not complete; keep partial evidence for local investigation. No production restore was attempted.',file=sys.stderr)
        raise SystemExit(1)
