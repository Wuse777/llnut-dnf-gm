"""Opt-in fixed release cleanup runner. No DB, shell, sockets or game access."""
from pathlib import Path
import json
import os
import pwd
import secrets
import stat
import time
from dnfgm.release_files import (OP, Refused, read_json, atomic_json, maintenance_lock,
                                 manifest, execute, canonical, reconcile_receipt)
import hashlib

BASE=Path('/opt/dnf-gm')
STATE=Path('/var/lib/dnf-gm/cleanup')
MANIFEST=Path('/run/dnf-gm/cleanup.json')
LOCK=Path('/var/lib/dnf-gm/maintenance.lock')


def secure_dir(path,mode,uid=0,gid=0):
    path.mkdir(mode=mode,parents=True,exist_ok=True)
    st=path.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid!=uid:raise Refused('unsafe_queue_directory')
    os.chown(path,uid,gid);os.chmod(path,mode)


def setup():
    if os.geteuid()!=0:raise Refused('root_worker_required')
    account=pwd.getpwnam('dnfgm')
    secure_dir(STATE,0o755)
    secure_dir(STATE/'private',0o700)
    secure_dir(STATE/'results',0o755)
    # App may create requests, never receipts, manifests, keys or release files.
    secure_dir(STATE/'inbox',0o770,0,account.pw_gid)
    path=STATE/'private'/'key'
    if not path.exists():
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as f:f.write(secrets.token_bytes(32));f.flush();os.fsync(f.fileno())
    st=path.lstat()
    if st.st_uid!=0 or st.st_mode & 0o077 or not stat.S_ISREG(st.st_mode) or st.st_nlink!=1:raise Refused('unsafe_signing_key')
    key=path.read_bytes()
    if len(key)!=32:raise Refused('invalid_signing_key')
    return key,account.pw_uid


def resources_ready():
    try:
        mem={line.split(':')[0]:int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith(('MemAvailable:','SwapFree:'))}
        live=read_json('/run/dnf-gm/status.json',owner=0)
        return (isinstance(live,dict) and live.get('core_ok') is True and
                0<=time.time()-live.get('collected_at',0)<45 and
                mem.get('MemAvailable',0)>=256*1024 and mem.get('SwapFree',0)>=1536*1024)
    except (OSError,ValueError,TypeError,IndexError):
        return False


def tick(base,state,manifest_path,lock_path,key,app_uid,*,owner=0):
    with maintenance_lock(lock_path):
        inbox=state/'inbox';results=state/'results';requests=[]
        with os.scandir(inbox) as entries:
            for index,entry in enumerate(entries):
                if index>=100:break
                if OP.fullmatch(entry.name.removesuffix('.json')) and entry.name.endswith('.json'):
                    requests.append(entry.name)
        # Bound actual removal to one previously confirmed task per invocation.
        for name in sorted(requests)[:1]:
            path=inbox/name;op=name[:-5];receipt_path=results/name
            request = None
            try:
                request=read_json(path,owner=app_uid)
                if not isinstance(request,dict) or request.get('operation_id')!=op:raise Refused('operation_mismatch')
                # Recovery is read/relabel only and must not depend on free swap.
                prior=reconcile_receipt(request,receipt_path,owner=owner)
                if prior is None:
                    if not resources_ready():raise Refused('resource_not_ready')
                    execute(base,request,key,receipt_path,owner=owner)
            except (OSError,ValueError,TypeError) as e:
                if not receipt_path.exists():
                    result={'operation_id':op,'state':'rejected','reason':str(e) if isinstance(e,Refused) else 'invalid_request','finished_at':time.time(),'items':[]}
                    # Bind readable requests; never echo paths or untrusted JSON.
                    if isinstance(request,dict):
                        result['request_sha256']=hashlib.sha256(canonical(request)).hexdigest()
                    atomic_json(receipt_path,result)
                else:
                    # Persistence/deletion errors can leave an executing receipt.
                    # Convert it to needs_review, never lose the recovery request.
                    reconcile_receipt(request,receipt_path,owner=owner)
            # Unlink only after a terminal/uncertain authoritative receipt exists.
            if receipt_path.exists():path.unlink(missing_ok=True)
        atomic_json(manifest_path,manifest(base,key,owner=owner))


def main():
    key,uid=setup()
    try:tick(BASE,STATE,MANIFEST,LOCK,key,uid)
    except BlockingIOError:
        print(json.dumps({'event':'cleanup_maintenance_busy'}))
    except Exception as e:
        print(json.dumps({'event':'cleanup_failed','error_type':type(e).__name__}))
        raise SystemExit(1)


if __name__=='__main__':main()
