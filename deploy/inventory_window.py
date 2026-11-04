"""Root-only maintenance permit lifecycle; deliberately cannot stop/start writers.

Use `close` successfully BEFORE resuming game services. An application commit
holds a shared lock; close fails busy rather than revoking mid-transaction.
"""
from contextlib import contextmanager
from pathlib import Path
import argparse
import fcntl
import math
import re
import os
import secrets
import time

from dnfgm.inventory_fence import (BOUND_FIELDS, MaintenanceFence, Refused, _read, directory,
                                  open_lock, read_permit, validate_permit)
from dnfgm.release_files import atomic_json, read_json
from inventory_probe import LinuxProbe

ROOT = Path('/run/dnf-gm/maintenance')
CONFIG = Path('/etc/dnf-gm/inventory-maintenance.json')


class WindowManager:
    def __init__(self,root,probe, *, owner=0,clock=time.time,sleep=time.sleep,monotonic=time.monotonic):
        self.root=Path(root);self.probe=probe;self.owner=owner;self.clock=clock;self.sleep=sleep;self.monotonic=monotonic

    def initialize(self):
        directory(self.root.parent,self.owner)
        try:self.root.mkdir(mode=0o755)
        except FileExistsError:pass
        directory(self.root,self.owner)
        try:
            fd=os.open(self.root/'fence.lock',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o644)
        except FileExistsError:
            fd=open_lock(self.root,self.owner)
        try:os.fsync(fd)
        finally:os.close(fd)
        # Never replace the lock, including after process restarts or expiry.
        fd=open_lock(self.root,self.owner);os.close(fd)

    @contextmanager
    def locked(self,exclusive):
        fd=open_lock(self.root,self.owner)
        try:
            try:fcntl.flock(fd,(fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)|fcntl.LOCK_NB)
            except BlockingIOError:raise Refused('maintenance_busy') from None
            before=os.fstat(fd);after=(self.root/'fence.lock').lstat()
            if (before.st_dev,before.st_ino)!=(after.st_dev,after.st_ino):raise Refused('maintenance_lock_changed')
            yield
        finally:os.close(fd)

    def checked_snapshot(self):
        sample=self.probe();now=self.clock()
        if (not isinstance(sample,dict) or any(sample.get(k) is not True for k in
                ('safe','all_writers_down','mysql_up','non_game_core_ok','no_unmanaged_processes'))):
            raise Refused('maintenance_not_proven')
        at=sample.get('collected_at')
        if (type(at) not in (int,float) or not math.isfinite(at) or not 0<=now-at<=20
                or not isinstance(sample.get('process_set_sha256'),str)
                or not re.fullmatch(r'[a-f0-9]{64}',sample['process_set_sha256'])):
            raise Refused('maintenance_evidence_stale')
        mono=self.monotonic();sample_mono=sample.get('collected_monotonic')
        if type(sample_mono) not in (int,float) or not math.isfinite(sample_mono) or not 0<=mono-sample_mono<=20:
            raise Refused('maintenance_evidence_stale')
        # Reuse the exact reader contract, without creating a file first.
        p={**{k:sample.get(k) for k in BOUND_FIELDS},'version':1,'id':'0'*32,
           'created_at':int(at),'expires_at':int(now)+30,'created_monotonic':sample_mono,'expires_monotonic':mono+30,'reason':'probe'}
        validate_permit(p,now,self.monotonic())
        for name,floor in [('mem_available_mib',256),('swap_free_mib',1536)]:
            if type(sample.get(name)) not in (int,float) or not floor<=sample[name]<float('inf'):
                raise Refused('maintenance_resources_low')
        return sample

    def issue(self, *, reason, ttl=600, acknowledge_writers_stopped=False):
        if acknowledge_writers_stopped is not True:raise Refused('maintenance_operator_ack_required')
        if type(ttl) is not int or not 30<=ttl<=3600:raise Refused('maintenance_ttl_invalid')
        if not isinstance(reason,str) or not 1<=len(reason.strip())<=200:raise Refused('maintenance_reason_required')
        with self.locked(True):
            # Even expired permits must be closed deliberately before a new one.
            if os.path.lexists(self.root/'permit.json'):raise Refused('maintenance_already_open')
            first=self.checked_snapshot();self.sleep(2);second=self.checked_snapshot()
            if any(first.get(k)!=second.get(k) for k in (*BOUND_FIELDS,'process_set_sha256')):
                raise Refused('maintenance_probe_changed')
            now=self.clock()
            p={**{k:second[k] for k in BOUND_FIELDS},'version':1,'id':secrets.token_hex(16),
               'created_at':int(first['collected_at']),'expires_at':int(first['collected_at'])+ttl,
               'created_monotonic':first['collected_monotonic'],'expires_monotonic':first['collected_monotonic']+ttl,'reason':reason.strip()}
            validate_permit(p,now,self.monotonic())
            e={**second,'permit_id':p['id']}
            # Evidence first: a crash cannot authorize using old evidence and a
            # new permit. Caller receiving a lost response must inspect, not retry.
            atomic_json(self.root/'evidence.json',e)
            atomic_json(self.root/'permit.json',p)
            return {'state':'issued','id':p['id'],'expires_at':p['expires_at']}

    def refresh(self):
        # Serialize writers; normally brief because hashes are cached. Reader
        # transactions block refresh, which leaves evidence to expire safely.
        with self.locked(True):
            p=read_permit(self.root,self.owner,self.clock(),self.monotonic())
            try:
                e=self.checked_snapshot()
                if any(e[k]!=p[k] for k in BOUND_FIELDS):raise Refused('maintenance_version_changed')
                # Recheck expiry after the probe, not just before it.
                validate_permit(p,self.clock(),self.monotonic())
                atomic_json(self.root/'evidence.json',{**e,'permit_id':p['id']})
                return {'state':'refreshed','id':p['id'],'expires_at':p['expires_at']}
            except Exception:
                # Atomic invalidation, no command/exception text in shared files.
                atomic_json(self.root/'evidence.json',{'safe':False,'permit_id':p['id'],
                    'collected_at':self.clock(),'reason':'maintenance_refresh_failed'})
                raise

    def close(self,expected_id):
        if not isinstance(expected_id,str) or len(expected_id)!=32:
            raise Refused('maintenance_id_required')
        with self.locked(True):
            try:p=_read(self.root,'permit.json',self.owner,4096)
            except FileNotFoundError:
                return {'state':'already_closed'}
            if not isinstance(p,dict) or p.get('id')!=expected_id:raise Refused('maintenance_window_changed')
            # No expiry check: closing an expired permit is always necessary.
            atomic_json(self.root/'evidence.json',{'safe':False,'permit_id':expected_id,
                'collected_at':self.clock(),'reason':'maintenance_closed'})
            (self.root/'permit.json').unlink()
            fd=os.open(self.root,os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(fd)
            finally:os.close(fd)
            return {'state':'closed','id':expected_id,'services_changed':False}


def main():
    parser=argparse.ArgumentParser(description='显式维护窗口；不会停止或启动任何游戏或核心服务')
    sub=parser.add_subparsers(dest='action',required=True)
    sub.add_parser('init');sub.add_parser('refresh');sub.add_parser('status')
    opening=sub.add_parser('issue');opening.add_argument('--reason',required=True)
    opening.add_argument('--ttl',type=int,default=600)
    opening.add_argument('--acknowledge-writers-stopped',action='store_true')
    closing=sub.add_parser('close');closing.add_argument('--id',required=True)
    args=parser.parse_args()
    if os.geteuid()!=0:parser.exit(1,'必须由服务器维护管理员在本机执行。\n')
    import json
    try:
        # Closing must not depend on a valid current config, live Docker, MySQL,
        # PVF or healthy proxies. It removes authority, never changes services.
        manager=WindowManager(ROOT,None)
        if args.action=='init':manager.initialize();result={'state':'initialized'}
        elif args.action=='close':result=manager.close(args.id)
        elif args.action=='status':
            p=read_permit(ROOT,now=time.time())
            fence=MaintenanceFence(ROOT,**{k:p[k] for k in ('image_digest','pvf_sha256','program_sha256')})
            result={'state':'verified',**fence.check()}
        else:
            directory(CONFIG.parent,0)
            manager.probe=LinuxProbe(read_json(CONFIG,owner=0,limit=65536))
            if args.action=='issue':result=manager.issue(reason=args.reason,ttl=args.ttl,
                acknowledge_writers_stopped=args.acknowledge_writers_stopped)
            else:result=manager.refresh()
        print(json.dumps(result,ensure_ascii=False))
    except Exception as error:
        # Process arguments/file contents may contain credentials. No tracebacks.
        code=str(error) if isinstance(error,Refused) else 'maintenance_probe_failed'
        print(json.dumps({'state':'refused','reason':code}))
        raise SystemExit(1) from None


class MonitorWindow:
    """Optional monitor adapter. Does not issue permits or start/stop anything."""
    def __init__(self,monitor_cfg):
        directory(CONFIG.parent,0)
        cfg=read_json(CONFIG,owner=0,limit=65536)
        probe=LinuxProbe(cfg)
        # Maintenance cannot omit another core service known by the normal
        # collector, or silently target a different container/PVF/component set.
        normalize=lambda n:n.removesuffix('.service')
        if (cfg['container']!=monitor_cfg['container'] or cfg['pvf_path']!=monitor_cfg['pvf_path']
                or set(cfg['components'])!=set(monitor_cfg['components'])
                or not {normalize(n) for n in monitor_cfg['core_services']} <= {normalize(n) for n in cfg['protected_services'].values()}):
            raise Refused('maintenance_monitor_config_mismatch')
        self.manager=WindowManager(ROOT,probe)
        self.fence=MaintenanceFence(ROOT,**{k:cfg[k] for k in ('image_digest','pvf_sha256','program_sha256')})

    def status(self):
        if not os.path.lexists(self.manager.root/'permit.json'):
            return {'active':False,'verified':False}
        try:
            self.manager.refresh()
            return {'active':True,'verified':True,**self.fence.check()}
        except Exception as error:
            return {'active':True,'verified':False,
                    'reason':str(error) if isinstance(error,Refused) else 'maintenance_probe_failed'}


if __name__=='__main__':main()
