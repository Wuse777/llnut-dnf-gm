"""Fixed complete maintenance outbox executor, not a generic command endpoint.

Entry requires installed-monitor proof; game exit, writer stop, window issue and
explicit close/restore use their original durable journals. The heartbeat only
reads journals/files: it never acquires DB connections or invokes game probes.
"""
from contextlib import contextmanager
from pathlib import Path
import threading

from dnfgm.release_files import Refused, atomic_json, read_json
from maintenance_drain import error_code, TERMINAL_FINISHED
from maintenance_outbox import PreparationWorker


class ExecutionWorker(PreparationWorker):
    def __init__(self, root, coordinator, app_uid, session, handshake, **kwargs):
        super().__init__(root,coordinator,app_uid,**kwargs)
        if (session.coordinator is not coordinator or coordinator.lifecycle is None
                or coordinator.admission is None or coordinator.lifecycle.host is not coordinator.host):
            raise Refused('maintenance_full_adapters_required')
        self.session,self.handshake=session,handshake
        # Recheck after transaction settlement and immediately before the first
        # game command. A timeout/failure leaves the frozen journal reviewable.
        coordinator.before_commands=self.before_commands

    def before_commands(self,plan):
        proof=self.handshake.check(self.coordinator.host.cfg,healthy=False)
        if proof.get('policy_sha256')!=plan['identity']['policy_sha256']:
            raise Refused('maintenance_monitor_policy_changed')

    def publish_status(self):
        cfg=self.coordinator.host.cfg
        active=self.coordinator._active()
        record=self.private_status(active) if active else None
        running=record and record['state'] not in {'prepared',*TERMINAL_FINISHED}
        supported=False;error=None
        try:
            # Restoration remains available for a known expired permit. Source,
            # process, protected core services and resources are still verified;
            # session.close_restore itself verifies original stopped writers.
            self.handshake.check(cfg,healthy=None if running else True)
            supported=True
        except (OSError,ValueError,TypeError,KeyError,RuntimeError) as exc:error=error_code(exc)
        atomic_json(self.root/'status.json',{'version':1,'collected_at':self.clock(),
            **{k:cfg[k] for k in ('image_digest','pvf_sha256','program_sha256')},
            'prepare_supported':True,'execute_supported':supported,'readiness_error':error,
            'executor_protocol':1})

    def report(self,data):
        result=self.private_status(data['operation_id'])
        if result is None:raise Refused('maintenance_journal_missing')
        prior=self.previous(data)
        if prior and 'observation' in prior:result={**result,'observation':prior['observation']}
        return self.publish(data,result)

    @contextmanager
    def heartbeat(self,data,interval=5):
        stop=threading.Event()
        def beat():
            while not stop.wait(interval):
                try:self.publish_status();self.report(data)
                except Exception:
                    # No fabricated success or automatic command replay. If the
                    # filesystem is unavailable the existing heartbeat expires.
                    pass
        thread=threading.Thread(target=beat,name='gm-maintenance-status',daemon=True)
        thread.start()
        try:yield
        finally:
            stop.set();thread.join(timeout=10)
            if thread.is_alive():raise Refused('maintenance_heartbeat_did_not_stop')

    def process(self,data):
        phase,op=data['phase'],data['operation_id']
        if phase not in ('confirm','close','recover'):return super().process(data)
        binding=self.bind(data)
        if binding['cancelled']:return super().process(data)
        record=self.private_status(op)
        if record is None:raise Refused('maintenance_plan_required')
        plan=self.coordinator._load(op)['plan']
        if data['fingerprint']!=plan['fingerprint']:raise Refused('maintenance_request_conflict')
        if phase=='recover':
            # Consume each explicit recovery attempt before any action. A queued
            # duplicate after a crash only reports; a new attempt needs new web
            # confirmation bound to the latest journal revision.
            path=self.root/'bindings'/(data['recovery_id']+'.recovery.json')
            identity={k:data[k] for k in ('operation_id','request_sha256','fingerprint','revision','recovery_id')}
            if path.exists():
                if read_json(path,owner=self.owner,limit=8192)!=identity:
                    raise Refused('maintenance_recovery_binding_changed')
                return self.report(data)
            if (record.get('revision')!=data['revision'] or not record.get('recovery_available')):
                return self.report(data)
            self.handshake.check(self.coordinator.host.cfg,healthy=None)
            atomic_json(path,identity,mode=0o600)
            with self.heartbeat(data):self.session.close_restore(op,recover=True)
            self.publish_status()
            return self.report(data)
        if phase=='confirm':
            # Repeated delivery after a start is QUERY ONLY, including a crash
            # between writers-stopped and issuing the maintenance window.
            if record['state']!='prepared':return self.report(data)
            if 'service_cycle' not in plan:raise Refused('maintenance_full_adapters_required')
            proof=self.handshake.check(self.coordinator.host.cfg)
            path=self.root/'bindings'/(op+'.execution.json')
            if path.exists():
                old=read_json(path,owner=self.owner,limit=16384)
                if old.get('fingerprint')!=plan['fingerprint'] or old.get('request_sha256')!=data['request_sha256']:
                    raise Refused('maintenance_execution_binding_changed')
            atomic_json(path,{'version':1,'fingerprint':plan['fingerprint'],
                'request_sha256':data['request_sha256'],'monitor':proof},mode=0o600)
            with self.heartbeat(data):
                result=self.coordinator.confirm(op,plan['fingerprint'])
                if result['state']=='writers_stopped':self.session.open(op)
        else:
            if record['state']=='completed':return self.report(data)
            # Do not turn a late close packet into a new open/stop operation.
            if record['state']!='maintenance_open':return self.report(data)
            self.handshake.check(self.coordinator.host.cfg,healthy=None)
            with self.heartbeat(data):self.session.close_restore(op)
        self.publish_status()
        return self.report(data)
