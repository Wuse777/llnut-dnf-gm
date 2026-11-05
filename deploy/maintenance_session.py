"""Root-only continuation: drained writers -> window -> close -> original services.

Not a web command endpoint. The outbox worker must not advertise full execution
until its monitor handshake, pre-drain outcome reconciliation and installation
are connected. Service commands never replay after a durable start intent.
"""
import copy
import hashlib

from dnfgm.inventory_fence import BOUND_FIELDS, _read
from dnfgm.inventory_reconcile import settle_window
from dnfgm.release_files import Refused, canonical, read_json
from maintenance_drain import error_code
from maintenance_session_state import load as load_session, steps as session_steps
from maintenance_admission import validate_token
from service_lifecycle import validate_cycle


class MaintenanceSession:
    def __init__(self, coordinator, window, health):
        self.coordinator, self.window, self.health = coordinator, window, health
        if not callable(health):raise Refused('maintenance_health_probe_required')
        if coordinator.lifecycle is None or coordinator.admission is None:
            raise Refused('maintenance_full_adapters_required')
        if window.owner != coordinator.owner:
            raise Refused('maintenance_owner_mismatch')

    def _plan(self, request_id):
        c=self.coordinator
        doc=c._load(request_id)
        if (doc['version']!=3 or doc['state'] not in ('writers_stopped','completed')
                or doc['state']!='completed' and c._active()!=request_id):
            raise Refused('maintenance_writers_not_stopped')
        plan=doc['plan'];validate_cycle(plan)
        token=validate_token(doc['events'][1]['data'],plan['admission'],request_id,plan['identity'])
        return plan,token

    def binding(self, plan):
        return {**{k:plan['identity'][k] for k in BOUND_FIELDS if k!='components'},
                'components':list(self.coordinator.host.cfg['components'])}

    steps = staticmethod(session_steps)

    def _save(self, doc):
        value={k:v for k,v in doc.items() if k!='digest'}
        value['digest']=hashlib.sha256(canonical(value)).hexdigest()
        self.coordinator._write('session-'+doc['request_id']+'.json',value)

    def _load(self, request_id, plan):
        return load_session(self.coordinator.root,self.coordinator.owner,request_id,plan)

    def _record(self, doc, plan, phase, data):
        steps=self.steps(plan);i=len(doc['events'])
        if i>=len(steps) or (phase,data.get('service'))!=steps[i]:
            raise Refused('maintenance_session_transition_invalid')
        at,mono=self.coordinator._now()
        updated=copy.deepcopy(doc);updated['events'].append({'phase':phase,'data':copy.deepcopy(data),'at':at,'monotonic':mono})
        updated['error']=None
        if phase=='window-issued':updated['state']='maintenance_open'
        elif phase=='window-close-intent':updated['state']='closing'
        elif phase=='window-closed':updated['state']='restoring'
        elif phase=='session-completed':updated['state']='completed'
        self._save(updated)
        doc.clear();doc.update(updated)

    def _failure(self, request_id, plan, error):
        # Saved-but-response-lost is reconciled from disk; never overwrite a
        # completed receipt, open another permit or replay a start command.
        doc=self._load(request_id,plan)
        if doc['state']!='completed':
            doc.update(state='needs_review',error=error_code(error));self._save(doc)
        return self.view(doc)

    @staticmethod
    def view(doc):
        return {'state':doc['state'],'request_id':doc['request_id'],
                'window_id':doc['request_id'],'fingerprint':doc['fingerprint'],
                'phase':doc['events'][-1]['phase'] if doc['events'] else None,
                'events':[{'sequence':i+1,'phase':e['phase'],'at':e['at'],'service':e['data'].get('service')}
                          for i,e in enumerate(doc['events'])],
                'error':doc['error'],'can_replay':False,'client_verified':False,
                # A durable issued receipt is not fresh evidence of validity.
                'window_requires_live_check':doc['state']=='maintenance_open'}

    def _database(self, plan):
        with self.coordinator.admission.db.connect() as connection,connection.cursor() as q:
            q.execute('SELECT @@server_uuid AS server_uuid')
            if q.fetchone()['server_uuid']!=plan['admission']['server_uuid']:
                raise Refused('maintenance_database_identity_changed')

    def open(self, request_id):
        c=self.coordinator
        with c.locked():
            plan,token=self._plan(request_id)
            try:return self.view(self._load(request_id,plan))
            except FileNotFoundError:pass
            c.admission.verify_frozen(token);self._database(plan)
            c.lifecycle.check(plan,c.lifecycle.stopped_snapshot(plan))
            doc={'version':1,'request_id':request_id,'fingerprint':plan['fingerprint'],
                 'state':'opening','events':[],'error':None}
            self._save(doc)
            try:
                self._record(doc,plan,'window-issue-intent',{'window_id':request_id})
                # Gate cannot be released while the original window is issued.
                with c.admission.gate.locked(False):
                    if c.admission.gate.read()!=token:raise Refused('maintenance_freeze_changed')
                    result=self.window.issue(reason=c._load(request_id)['reason'],window_id=request_id,
                        expected_binding=self.binding(plan),acknowledge_writers_stopped=True)
                self._record(doc,plan,'window-issued',result)
                return self.view(doc)
            except Exception as error:return self._failure(request_id,plan,error)

    def _window_matches(self, request_id, plan):
        # Expired windows may still be closed. Do not use read_permit's freshness
        # validation to prevent revocation of an expired but correctly bound one.
        with self.window.locked(False):
            p=_read(self.window.root,'permit.json',self.window.owner,4096)
            if p.get('id')!=request_id or any(p.get(k)!=v for k,v in self.binding(plan).items()):
                raise Refused('maintenance_original_window_changed')
            return p

    def close_restore(self, request_id):
        c=self.coordinator
        with c.locked():
            plan,token=self._plan(request_id);doc=self._load(request_id,plan)
            # Only an explicit first close initiates service restoration. Other
            # states remain query-only; unknown command effects are not replayed.
            if doc['state']=='completed':
                self._retire(doc,plan)
                return self.view(doc)
            if doc['state']!='maintenance_open':return self.view(doc)
            c.admission.verify_frozen(token);self._database(plan)
            self._window_matches(request_id,plan)
            c.lifecycle.check(plan,c.lifecycle.stopped_snapshot(plan))
            try:
                self._record(doc,plan,'window-close-intent',{'window_id':request_id})
                previous=self.window.reconcile
                self.window.reconcile=lambda wid:settle_window(c.admission.db,wid,
                    expected_server_uuid=plan['admission']['server_uuid'])
                try:closed=self.window.close(request_id,expected_binding=self.binding(plan))
                finally:self.window.reconcile=previous
                self._record(doc,plan,'window-closed',closed)
                with self.window.closed_guard(request_id,expected_binding=self.binding(plan)) as closed_proof:
                    def proof():
                        closed_proof();c.admission.verify_frozen(token);self._database(plan)
                        return True
                    def record(phase,data):
                        proof();self._record(doc,plan,phase,data)
                    restored=c.lifecycle.restore(plan,record,proof)
                    self._record(doc,plan,'gate-release-intent',{'window_id':request_id})
                    def restored_proof():
                        closed_proof();self._database(plan)
                        health=self.health()
                        if (not isinstance(health,dict) or health.get('core_ok') is not True
                                or health.get('services',{}).get('dnf_gateway') is not True
                                or any(health.get(k)!=plan['identity'][k] for k in ('image_digest','pvf_sha256'))):
                            raise Refused('maintenance_restored_core_unhealthy')
                        c.lifecycle.check(plan,restored)
                        for name in plan['service_cycle']['entries']:
                            saved=next(e['data']['process'] for e in doc['events']
                                if e['phase']=='service-restored' and e['data']['service']==name)
                            if c.host.service_process(plan['identity'],restored[name][4])!=saved:
                                raise Refused('maintenance_restored_process_changed')
                        return True
                    released=c.admission.gate.release(token,verify_restored=restored_proof)
                    self._record(doc,plan,'gate-released',released)
                    self._record(doc,plan,'session-completed',{'window_id':request_id})
                self._retire(doc,plan)
                return self.view(doc)
            except Exception as error:return self._failure(request_id,plan,error)

    def _retire(self, session, plan):
        """Finish logical ownership only after durable close/restore/release.

        Called under coordinator.locked(). Retrying this final bookkeeping never
        repeats a game command. Historical completed requests stay readable even
        when a later request owns the gate.
        """
        c=self.coordinator;request_id=session['request_id'];raw=c._load(request_id)
        if raw['state']=='completed':return
        verified=self._load(request_id,plan)
        if verified['state']!='completed' or c._active()!=request_id:
            raise Refused('maintenance_completion_unproven')
        released=next(e['data'] for e in verified['events'] if e['phase']=='gate-released')
        expected=copy.deepcopy(plan['services_before'])
        records=[e['data'] for e in verified['events'] if e['phase']=='service-restored']
        for item in records:expected[item['service']]=item['state']
        with self.window.closed_guard(request_id,expected_binding=self.binding(plan)):
            with c.admission.gate.locked(False):
                if c.admission.gate.read()!=released:raise Refused('maintenance_completion_gate_changed')
                self._database(plan)
                health=self.health()
                if (health.get('core_ok') is not True or health.get('services',{}).get('dnf_gateway') is not True
                        or any(health.get(k)!=plan['identity'][k] for k in ('image_digest','pvf_sha256'))):
                    raise Refused('maintenance_restored_core_unhealthy')
                c.lifecycle.check(plan,expected)
                for item in records:
                    if c.host.service_process(plan['identity'],item['state'][4])!=item['process']:
                        raise Refused('maintenance_restored_process_changed')
                raw.update(state='completed',updated_at=c._now()[0])
                c._write(request_id+'.json',raw)

    def status(self, request_id):
        plan,_=self._plan(request_id)
        return self.view(self._load(request_id,plan))


class RestoredHealth:
    """Reuse the fixed normal collector, never its maintenance exception.

    Reads root-owned configuration, checks numeric loopback HTTP without proxy
    or redirects, and cannot initiate a maintenance refresh under our own lock.
    """
    def __init__(self, host, config=None, *, owner=0):
        from monitor import Collector, CONFIG, validate
        cfg=validate(read_json(config or CONFIG,owner=owner,limit=65536))
        if (cfg['container']!=host.cfg['container'] or cfg['pvf_path']!=host.cfg['pvf_path']
                or not set(cfg['components'])<=set(host.cfg['components'])):
            raise Refused('maintenance_health_config_mismatch')
        self.collect=Collector({**cfg,'inventory_maintenance_enabled':False})

    def __call__(self):return self.collect()
