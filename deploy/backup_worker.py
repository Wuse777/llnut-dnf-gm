"""Management-only online snapshots in the existing single root worker.

No process/service commands. Never runs alongside another worker DB operation.
The shared deployment lock prevents approved migrations during a snapshot.
"""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import time
import uuid
import pymysql
from dnfgm.alerts import atomic
from dnfgm.backup import dump,canonical
from dnfgm.backup_health import private_receipt,verify_evidence,validate_receipt
from dnfgm.backup_schedule import BackupSchedule,daily_key,policy_view
from dnfgm.catalog import snapshot
from dnfgm.release_files import Refused
from dnfgm.service import one,dump as json_dump

ROOT=Path('/var/backups/dnf-gm/automatic')
CONFIG=Path('/etc/dnf-gm/backup.json')


def private_directory(path,owner=0):
    st=Path(path).lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid!=owner or st.st_mode&0o077:raise Refused('backup_directory_untrusted')


def configuration(path,settings,owner=0):
    st=Path(path).lstat()
    if st.st_uid!=owner:raise Refused('backup_config_untrusted')
    d=private_receipt(path)
    if set(d)!={'version','host','port','user','password'} or d['version']!=1 or d['user']!='root' or not isinstance(d['password'],str) or not d['password']:
        raise Refused('backup_config_untrusted')
    if (d['host'],d['port'])!=(settings.db_host,settings.db_port):raise Refused('backup_database_changed')
    return d


def write_receipt(path,value):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as f:f.write(canonical(value)+b'\n');f.flush();os.fsync(f.fileno())


class BackupWorker:
    def __init__(self,db,settings,*,root=ROOT,config=CONFIG,lock=Path('/var/lib/dnf-gm/maintenance.lock'),owner=0,
                 guard=None,connect=None,clock=time.time):
        self.db,self.settings=db,settings;self.control=BackupSchedule(db,settings)
        self.root,self.config,self.lock=map(Path,(root,config,lock));self.owner=owner
        self.clock=clock;self.next_poll=0
        self.guard=guard or self._guard
        self.connect=connect or self._connect

    def _connect(self):
        d=configuration(self.config,self.settings,self.owner)
        return pymysql.connect(host=d['host'],port=d['port'],user=d['user'],password=d['password'],
            charset='utf8mb4',autocommit=False,connect_timeout=3,read_timeout=10,write_timeout=10,local_infile=False)

    def _guard(self):
        from check_maintenance_idle import assert_idle,assert_config_gate
        assert_idle();assert_config_gate()
        state=snapshot(self.settings)
        if (not state.get('fresh') or state.get('mem_available_mib',0)<256 or
                state.get('swap_free_mib',0)<1536 or state.get('disk_free_gib',0)<2):
            raise Refused('backup_resources_low')

    def report(self,policy,state='ready',reason=None,failure=False):
        atomic(self.control.status_path,{'version':1,'checked_at':self.clock(),'state':state,
            'configured':state!='unconfigured','alerts_enabled':bool(policy.get('failure_alerts',1)),
            'failure':failure,'reason':reason},mode=0o644)

    def latest_failure(self,q):
        row=one(q,"SELECT state,result_json FROM dnf_gm.backup_runs WHERE state IN ('succeeded','failed') ORDER BY finished_at DESC,run_id DESC LIMIT 1")
        return bool(row and (row['state']=='failed' or json.loads(row.get('result_json') or '{}').get('retention_failed')))

    def claim(self):
        now=self.clock()
        with self.db.connect() as c,c.cursor() as q:
            policy=self.control.policy(q,True)
            prior=one(q,"SELECT * FROM dnf_gm.backup_runs WHERE state='running' ORDER BY created_at,run_id LIMIT 1 FOR UPDATE")
            if prior:self.validate_run(prior);return policy,prior,True
            queued=one(q,"SELECT * FROM dnf_gm.backup_runs WHERE state='queued' ORDER BY created_at,run_id LIMIT 1 FOR UPDATE")
            key=daily_key(policy,now)
            if not queued and key and not one(q,'SELECT run_id FROM dnf_gm.backup_runs WHERE run_key=%s',(key,)):
                run_id=uuid.uuid4().hex
                q.execute("INSERT INTO dnf_gm.backup_runs(run_id,run_key,origin,state,reason,spec_json,created_at) VALUES(%s,%s,'daily','queued','每日GM管理库备份',%s,%s)",(run_id,key,json_dump(policy_view(policy)),now))
                queued=one(q,'SELECT * FROM dnf_gm.backup_runs WHERE run_id=%s',(run_id,))
            if queued:
                self.validate_run(queued)
                q.execute("UPDATE dnf_gm.backup_runs SET state='running',started_at=%s WHERE run_id=%s",(now,queued['run_id']))
                q.execute("INSERT INTO dnf_gm.audit(operation_id,actor,action,reason,request_json,result_json) VALUES(%s,'maintenance','backup-start',%s,%s,%s)",('backup-start:'+queued['run_id'],queued['reason'],json_dump({'run_id':queued['run_id'],'origin':queued['origin']}),json_dump({'state':'running'})))
                c.commit();queued['state']='running';queued['started_at']=now
            return policy,queued,False

    @staticmethod
    def validate_run(row):
        if not re.fullmatch(r'[a-f0-9]{32}',row['run_id']) or row['origin'] not in ('manual','daily'):
            raise Refused('backup_request_untrusted')
        spec=json.loads(row['spec_json'])
        if type(spec.get('retention_days')) is not int or not 1<=spec['retention_days']<=30:
            raise Refused('backup_request_untrusted')

    def finish(self,run_id,result=None,error=None):
        with self.db.connect() as c,c.cursor() as q:
            row=one(q,'SELECT * FROM dnf_gm.backup_runs WHERE run_id=%s FOR UPDATE',(run_id,))
            if not row or row['state']!='running':return
            state='failed' if error else 'succeeded';now=self.clock()
            q.execute('UPDATE dnf_gm.backup_runs SET state=%s,finished_at=%s,result_json=%s,error_code=%s WHERE run_id=%s',
                (state,now,json_dump(result) if result else None,error,run_id))
            q.execute("INSERT INTO dnf_gm.audit(operation_id,actor,action,reason,request_json,result_json) VALUES(%s,'maintenance','backup-finish',%s,%s,%s)",
                ('backup-finish:'+run_id,row['reason'],json_dump({'run_id':run_id}),json_dump({'state':state,'error_code':error,'result':result})))
            c.commit()

    def publish(self,folder):
        private_directory(folder,self.owner)
        receipt=validate_receipt(private_receipt(folder/'backup-receipt.json'),'backup')
        # A new daily snapshot must not erase the previous recovery rehearsal.
        # Different hashes remain explicitly "other_artifact", never green for
        # this snapshot. The root-owned private receipt is installed separately.
        restored=Path(self.settings.backup_health_file).parent/'restore-receipt.json'
        evidence=verify_evidence(folder/'management.ndjson',folder/'backup-receipt.json',
            restored if os.path.lexists(restored) else None,now=self.clock())
        if evidence['integrity']!='verified':raise Refused('backup_verification_failed')
        atomic(Path(self.settings.backup_health_file),evidence,mode=0o644)
        return {k:receipt[k] for k in ('completed_at','artifact_sha256','bytes','tables','rows','scope')}|{
            'consistency':'innodb_consistent_snapshot',
            'restore_verified':(evidence.get('restore') or {}).get('state')=='verified','offsite_copy':False}

    def retention(self,days):
        entries=[]
        for folder in self.root.iterdir():
            if not re.fullmatch(r'management-[a-f0-9]{32}',folder.name):continue
            try:
                private_directory(folder,self.owner)
                names={p.name for p in folder.iterdir()}
                if names!={'management.ndjson','backup-receipt.json'}:continue
                for path in folder.iterdir():
                    st=path.lstat()
                    if not stat.S_ISREG(st.st_mode) or st.st_uid!=self.owner or st.st_mode&0o077:raise ValueError('Untrusted file')
                r=validate_receipt(private_receipt(folder/'backup-receipt.json'),'backup')
                entries.append((r['completed_at'],folder))
            except (OSError,ValueError,TypeError,KeyError):continue
        entries.sort(reverse=True);deleted=0;cutoff=self.clock()-days*86400
        for completed,folder in entries[2:]:
            if completed<cutoff:
                # Fixed private generated folders only; never legacy/manual/unknown files.
                (folder/'management.ndjson').unlink();(folder/'backup-receipt.json').unlink();folder.rmdir();deleted+=1
        return deleted

    def tick(self,*,force=False):
        if not force and time.monotonic()<self.next_poll:return
        self.next_poll=time.monotonic()+30
        with self.db.connect() as c,c.cursor() as q:
            policy=self.control.policy(q);failure=self.latest_failure(q)
        if not self.config.exists():self.report(policy,'unconfigured','backup_configuration_missing',True);return
        private_directory(self.root,self.owner);configuration(self.config,self.settings,self.owner)
        fd=os.open(self.lock,os.O_RDWR|os.O_NOFOLLOW)
        try:
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:self.report(policy,'deferred','maintenance_busy',failure);return
            try:self.guard()
            except Exception as error:
                reason='resources_low' if str(error)=='backup_resources_low' else 'maintenance_busy'
                self.report(policy,'deferred',reason,failure);return
            policy,row,recovery=self.claim()
            if not row:self.report(policy,failure=failure);return
            self.report(policy,'running',failure=failure)
            folder=self.root/('management-'+row['run_id'])
            try:
                if not recovery:
                    folder.mkdir(mode=0o700)
                    # The worker's app-account DB connection has already CLOSED.
                    # The root read-only snapshot is the single third connection.
                    c=self.connect()
                    try:receipt=dump(c,folder/'management.ndjson',budget=90)
                    finally:c.close()
                    write_receipt(folder/'backup-receipt.json',receipt)
                elif not (folder/'backup-receipt.json').is_file():
                    self.finish(row['run_id'],error='backup_interrupted');self.report(policy,'error','backup_interrupted',True);return
                try:result=self.publish(folder)
                except Exception:
                    self.finish(row['run_id'],error='backup_verification_failed');self.report(policy,'error','backup_worker_failed',True);return
                try:result['retention_deleted']=self.retention(json.loads(row['spec_json'])['retention_days'])
                except Exception:result['retention_failed']=True
                self.finish(row['run_id'],result)
                self.report(policy,failure=result.get('retention_failed',False))
            except Exception:
                # A committed file/receipt is reconciled on the NEXT tick, never
                # exported again. If no receipt exists, mark an explicit failure.
                if not (folder/'backup-receipt.json').is_file():self.finish(row['run_id'],error='backup_failed')
                self.report(policy,'error','backup_worker_failed',True)
        finally:os.close(fd)
