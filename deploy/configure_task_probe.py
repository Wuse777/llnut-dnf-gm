#!/usr/bin/env python3
"""Root-only private token preparation. No service commands or token output.

prepare is resumable: a token saved to either file is reused, not rotated.
enable requires a successful authenticated aggregate read from the running GM.
"""
import argparse
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import pwd
import secrets
import stat
import sys
import tempfile
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from dnfgm.config import Settings
from dnfgm.task_probe import valid_token, validate_summary
from alert_worker import task_health, validate_config

APP = Path('/etc/dnf-gm/config.json')
OBSERVER = Path('/etc/dnf-gm-alerts.json')


def read_private(path, owners, mask):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as stream:
        st = os.fstat(stream.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid not in owners or st.st_mode & mask or st.st_size > 262144:
            raise ValueError('Invalid private configuration ownership, mode or size')
        raw = stream.read(262145)
        if len(raw)>262144:raise ValueError('Oversized private configuration')
    value=json.loads(raw)
    if not isinstance(value,dict):raise ValueError('Invalid private configuration')
    return value,st,hashlib.sha256(raw).digest()


def replace_private(path, value, original, owners, mask):
    _,st,digest=original
    current=read_private(path,owners,mask)
    if (current[1].st_ino,current[1].st_dev,current[2]) != (st.st_ino,st.st_dev,digest):
        raise ValueError('Configuration changed; reread before retrying')
    body=(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode()
    if len(body)>262144:raise ValueError('Oversized private configuration')
    fd,name=tempfile.mkstemp(prefix='.'+path.name+'-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            os.fchown(stream.fileno(),st.st_uid,st.st_gid)
            os.fchmod(stream.fileno(),stat.S_IMODE(st.st_mode))
            stream.write(body);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
        directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:
        if os.path.exists(name):os.unlink(name)


def configure(mode, *, app_path=APP, observer_path=OBSERVER, app_owners=None, observer_owners=(0,), probe=task_health):
    app_owners=app_owners if app_owners is not None else (0,pwd.getpwnam('dnfgm').pw_uid)
    original_app=read_private(app_path,app_owners,0o027)
    original_observer=read_private(observer_path,observer_owners,0o027)
    app,observer=dict(original_app[0]),dict(original_observer[0])
    Settings(**app).check();validate_config(observer)
    if mode=='disable':
        if observer.get('task_health_enabled') is not False:
            observer['task_health_enabled']=False
            replace_private(observer_path,observer,original_observer,observer_owners,0o027)
        return {'mode':'disabled','service_restart':False}
    a,b=app.get('task_probe_token',''),observer.get('task_probe_token','')
    if a and b and not hmac.compare_digest(a,b):
        raise ValueError('Probe credentials differ; no automatic rotation or overwrite')
    token=a or b
    if mode=='enable':
        if not valid_token(a) or not valid_token(b):raise ValueError('Prepare matching private tokens first')
        result=validate_summary(probe(observer),time.time())
        if result['state']=='unknown' or result['truncated']:
            raise ValueError('Running task probe has incomplete evidence; diagnose before enabling')
        observer['task_health_enabled']=True
        validate_config(observer)
        if observer!=original_observer[0]:
            replace_private(observer_path,observer,original_observer,observer_owners,0o027)
        return {'mode':'enabled','service_restart':False}
    if mode!='prepare':raise ValueError('Unknown configuration mode')
    token=token or secrets.token_hex(32)
    app['task_probe_token']=token
    observer['task_probe_token']=token
    observer.setdefault('task_health_enabled',False)
    Settings(**app).check();validate_config(observer)
    # Write application first. An interrupted second write is repaired by the
    # next prepare using the same first-file token. Never print or rotate it.
    if app!=original_app[0]:replace_private(app_path,app,original_app,app_owners,0o027)
    if observer!=original_observer[0]:replace_private(observer_path,observer,original_observer,observer_owners,0o027)
    return {'mode':'prepared','gm_may_need_reload':True,'service_restart':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('prepare','enable','disable'))
    args=parser.parse_args()
    if os.geteuid()!=0:raise SystemExit('Root required')
    fd=os.open('/run/lock/dnf-gm-task-probe.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as lock:
        st=os.fstat(lock.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=0 or st.st_mode&0o077:raise ValueError('Invalid preparation lock')
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        result=configure(args.mode)
    print(json.dumps(result))


if __name__=='__main__':
    try:main()
    except Exception:
        # Underlying JSON, HTTP and file errors may contain credentials.
        print('{"error":"task_probe_setup_failed","action":"inspect_private_configuration_and_running_version"}',file=sys.stderr)
        raise SystemExit(1)
