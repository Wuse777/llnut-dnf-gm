"""Read-only restore transition proof; no database, signals, writes or renewals."""
import os
from pathlib import Path

from dnfgm.inventory_fence import BOUND_FIELDS, MAX_CLOSE_BYTES, _read, validate_permit
from dnfgm.release_files import Refused
from maintenance_gate import WriteGateManager
from maintenance_session_state import bound_to_plan, load
from service_lifecycle import START_TIMEOUT, validate_cycle


class SessionMonitor:
    def __init__(self, coordinator, runtime_root, *, required_components=()):
        self.c,self.runtime=coordinator,Path(runtime_root)
        self.required_components=tuple(required_components)

    def observe(self,plan,session):
        h=self.c.host;cycle=validate_cycle(plan)
        if h.identity()!=plan['identity']:raise Refused('maintenance_restore_target_changed')
        states=h.services();before=plan['services_before']
        if set(states)!=set(before) or any(list(states[n])!=before[n] for n in cycle['unchanged']):
            raise Refused('maintenance_restore_unrelated_service_changed')
        latest={e['data']['service']:e for e in session['events'] if 'service' in e['data']}
        result=[]
        for name,entry in cycle['entries'].items():
            if h.contract(plan['identity'],name)!=entry['contract']:raise Refused('maintenance_service_contract_changed')
            row=list(states[name]);event=latest.get(name);phase=event['phase'] if event else None
            stopped=[False,False,False,True,-1]
            marked=[False,False,entry['before'][2],True,-1]
            state='changed'
            if phase is None and row==stopped:state='down_waiting_restore'
            elif phase=='restore-marker-intent' and row in (stopped,marked):state='restore_marker_pending'
            elif phase=='restore-marker-applied' and row==marked:state='restore_start_pending'
            elif phase in ('restore-start-intent','restore-start-sent'):
                if row==marked:state='restore_start_pending'
                elif row[0] and row[1] and row[2]==entry['before'][2] and row[4]>0:
                    process=h.service_process(plan['identity'],row[4])
                    if process['program_sha256']==entry['process']['program_sha256']:state='starting'
            elif phase=='service-restored':
                if row==event['data']['state'] and h.service_process(plan['identity'],row[4])==event['data']['process']:
                    state='restored'
            result.append({'service':name,'state':state})
        if h.identity()!=plan['identity'] or h.services()!=states:raise Refused('maintenance_restore_observation_changed')
        return result

    def recovery(self, window):
        """Keep explicit restoration reachable after expiry; never renew write authority."""
        c=self.c; request_id=c._active()
        if request_id is None:raise Refused('maintenance_recovery_not_open')
        raw=c._load(request_id);plan=raw['plan']
        session=load(c.root,c.owner,request_id,plan)
        if raw['version']!=3 or raw['state']!='writers_stopped' or (session['state'] not in ('maintenance_open','needs_review','closing') or not 2<=len(session['events'])<=3):
            raise Refused('maintenance_recovery_not_open')
        permit=_read(self.runtime,'permit.json',c.owner,4096)
        # Validate original shape and lifetime, NOT permission at the current time.
        validate_permit(permit,permit.get('created_at'),permit.get('created_monotonic'))
        now,mono=c._now()
        if (now<permit['created_at'] or mono<permit['created_monotonic'] or
                (now<permit['expires_at'] and mono<permit['expires_monotonic'])):
            raise Refused('maintenance_recovery_not_expired')
        issued=next(e['data'] for e in session['events'] if e['phase']=='window-issued')
        binding={k:permit[k] for k in BOUND_FIELDS}
        if (permit['id']!=request_id or issued['id']!=request_id or
                issued['expires_at']!=permit['expires_at'] or not bound_to_plan(binding,plan)):
            raise Refused('maintenance_original_window_changed')
        original=plan['services_before'];games=set(plan['service_cycle']['games'])
        if any(name not in original or (name not in games and
                (original[name][:3]!=[True,True,True] or original[name][4]<1)) for name in self.required_components):
            raise Refused('maintenance_preexisting_component_failure')
        gate=c.admission.gate if c.admission else WriteGateManager('/var/lib/dnf-gm/write-gate',owner=c.owner)
        expected=raw['events'][1]['data']
        with gate.locked(False):
            if gate.read()!=expected:raise Refused('maintenance_restore_gate_changed')
        sample=window.checked_snapshot()
        if any(sample.get(k)!=v for k,v in binding.items()):raise Refused('maintenance_restore_target_changed')
        services=self.observe(plan,session)
        if any(row['state']!='down_waiting_restore' for row in services):
            raise Refused('maintenance_restore_unexpected_state')
        if (c._active()!=request_id or c._load(request_id)!=raw or
                load(c.root,c.owner,request_id,plan)!=session or
                _read(self.runtime,'permit.json',c.owner,4096)!=permit):
            raise Refused('maintenance_restore_journal_changed')
        with gate.locked(False):
            if gate.read()!=expected:raise Refused('maintenance_restore_gate_changed')
        after,after_mono=c._now()
        if not (0<=after-now<=20 and 0<=after_mono-mono<=20):
            raise Refused('maintenance_evidence_stale')
        return {'active':True,'verified':True,'authority':'recovery-only',
                'request_id':request_id,'phase':session['state'],'maintenance_permit':False,
                'write_window_expired':True,'collected_at':now,'expires_at':now+30,'services':services}

    def interrupted(self, request_id, raw, session):
        """Fresh read-only recovery visibility, never renewed game-write authority.

        No duration extension of an old transition: re-read original identities,
        the closed window, gate and every process at each collection instead.
        """
        c=self.c;plan=raw['plan'];now,mono=c._now()
        if raw['state']!='writers_stopped' or len(session['events'])<3:
            raise Refused('maintenance_recovery_not_closed')
        if any(now<e['at'] or mono<e['monotonic'] for e in session['events']):
            raise Refused('maintenance_evidence_stale')
        if os.path.lexists(self.runtime/'permit.json'):return None
        closed=_read(self.runtime,'closed.json',c.owner,MAX_CLOSE_BYTES)
        if (closed.get('id')!=request_id or not bound_to_plan(closed.get('binding'),plan)
                or type(closed.get('safe_to_resume')) is not bool
                or len(session['events'])>=4 and closed['safe_to_resume'] is not True):
            raise Refused('maintenance_close_not_proven')
        original=plan['services_before'];games=set(plan['service_cycle']['games'])
        if any(name not in original or (name not in games and
                (original[name][:3]!=[True,True,True] or original[name][4]<1)) for name in self.required_components):
            raise Refused('maintenance_preexisting_component_failure')
        gate=c.admission.gate if c.admission else WriteGateManager('/var/lib/dnf-gm/write-gate',owner=c.owner)
        frozen=raw['events'][1]['data'];phases={e['phase'] for e in session['events']}
        released=next((e['data'] for e in session['events'] if e['phase']=='gate-released'),None)
        with gate.locked(False):
            current=gate.read()
            if released:
                if current!=released:raise Refused('maintenance_restore_gate_changed')
            elif current!=frozen:
                if ('gate-release-intent' not in phases or current['state']!='open'
                        or any(current[k]!=frozen[k] for k in ('generation','operation_id','binding_sha256'))):
                    raise Refused('maintenance_restore_gate_changed')
        services=self.observe(plan,session)
        if any(row['state']=='changed' for row in services):raise Refused('maintenance_restore_unexpected_state')
        if (c._active()!=request_id or c._load(request_id)!=raw
                or load(c.root,c.owner,request_id,plan)!=session
                or _read(self.runtime,'closed.json',c.owner,MAX_CLOSE_BYTES)!=closed
                or os.path.lexists(self.runtime/'permit.json')):
            raise Refused('maintenance_restore_journal_changed')
        with gate.locked(False):
            if gate.read()!=current:raise Refused('maintenance_restore_gate_changed')
        after,after_mono=c._now()
        if not (0<=after-now<=20 and 0<=after_mono-mono<=20):raise Refused('maintenance_evidence_stale')
        return {'active':True,'verified':True,'authority':'recovery-only','request_id':request_id,
                'phase':session['state'],'maintenance_permit':False,'recovery_required':True,
                'collected_at':now,'expires_at':now+30,'services':services}

    def prewindow(self, request_id, raw, session):
        """Fresh all-writers-stopped evidence, including a lost issue receipt.

        Grants visibility for explicit restoration only, never game-write access.
        Partial drains and live writers deliberately do not qualify.
        """
        c=self.c;plan=raw['plan'];now,mono=c._now()
        if raw['state']!='writers_stopped':raise Refused('maintenance_writers_not_stopped')
        if now<raw['started_at'] or mono<raw['started_monotonic']:raise Refused('maintenance_evidence_stale')
        before=plan['services_before'];games=set(plan['service_cycle']['games'])
        if any(n not in before or (n not in games and (before[n][:3]!=[True,True,True] or before[n][4]<1)) for n in self.required_components):
            raise Refused('maintenance_preexisting_component_failure')
        gate=c.admission.gate if c.admission else WriteGateManager('/var/lib/dnf-gm/write-gate',owner=c.owner)
        frozen=raw['events'][1]['data']
        with gate.locked(False):
            if gate.read()!=frozen:raise Refused('maintenance_restore_gate_changed')
        def optional(name,limit):
            try:return _read(self.runtime,name,c.owner,limit)
            except FileNotFoundError:return None
        permit=optional('permit.json',4096);closed=optional('closed.json',MAX_CLOSE_BYTES)
        if permit:
            if not session or not session['events'] or session['events'][0]['phase']!='window-issue-intent':
                raise Refused('maintenance_window_without_intent')
            validate_permit(permit,permit.get('created_at'),permit.get('created_monotonic'))
            if permit['id']!=request_id or not bound_to_plan({k:permit[k] for k in BOUND_FIELDS},plan):
                raise Refused('maintenance_original_window_changed')
        elif closed and closed.get('id')==request_id:
            if not bound_to_plan(closed.get('binding'),plan):raise Refused('maintenance_original_window_changed')
        elif closed and closed.get('safe_to_resume') is not True:
            raise Refused('maintenance_previous_close_unresolved')
        services=self.observe(plan,session or {'events':[]})
        if any(row['state']!='down_waiting_restore' for row in services):raise Refused('maintenance_restore_unexpected_state')
        try:after_session=load(c.root,c.owner,request_id,plan)
        except FileNotFoundError:after_session=None
        if (c._active()!=request_id or c._load(request_id)!=raw or after_session!=session
                or optional('permit.json',4096)!=permit or optional('closed.json',MAX_CLOSE_BYTES)!=closed):
            raise Refused('maintenance_restore_journal_changed')
        with gate.locked(False):
            if gate.read()!=frozen:raise Refused('maintenance_restore_gate_changed')
        after,after_mono=c._now()
        if not (0<=after-now<=20 and 0<=after_mono-mono<=20):raise Refused('maintenance_evidence_stale')
        return {'active':True,'verified':True,'authority':'recovery-only','request_id':request_id,
                'phase':'prewindow-recovery','maintenance_permit':False,'recovery_required':True,
                'collected_at':now,'expires_at':now+30,'services':services}

    def status(self):
        c=self.c
        if not os.path.lexists(c.root):return None
        request_id=c._active()
        if request_id is None:return None
        raw=c._load(request_id);plan=raw['plan']
        if raw['version']!=3 or raw['state'] not in ('writers_stopped','completed'):return None
        try:session=load(c.root,c.owner,request_id,plan)
        except FileNotFoundError:
            if raw['state']=='completed':raise Refused('maintenance_completion_missing')
            return self.prewindow(request_id,raw,None)
        if raw['state']=='completed':return {'active':False,'verified':False,'recorded_state':'completed'}
        if len(session['events'])<2 or len(session['events'])<=3 and session['events'][1]['phase']=='window-not-issued':
            return self.prewindow(request_id,raw,session)
        closing=next((e for e in session['events'] if e['phase']=='window-close-intent'),None)
        if closing is None:return None
        if session['state'] in ('needs_review','completed'):
            return self.interrupted(request_id,raw,session)
        now,mono=c._now();duration=len(plan['service_cycle']['start_order'])*(START_TIMEOUT+10)+120
        result={'active':True,'verified':False,'authority':'restore-transition',
                'request_id':request_id,'phase':session['state'],'maintenance_permit':False,
                'collected_at':now,'expires_at':closing['at']+duration}
        if not (0<=now-closing['at']<duration and 0<=mono-closing['monotonic']<duration):
            return self.interrupted(request_id,raw,session)
        original=plan['services_before'];games=set(plan['service_cycle']['games'])
        if any(name not in original or (name not in games and
                (original[name][:3]!=[True,True,True] or original[name][4]<1)) for name in self.required_components):
            result['reason']='maintenance_preexisting_component_failure';return result
        if os.path.lexists(self.runtime/'permit.json'):
            # The normal window adapter owns observations before revocation.
            return None
        closed=_read(self.runtime,'closed.json',c.owner,MAX_CLOSE_BYTES)
        if (closed.get('id')!=request_id or not bound_to_plan(closed.get('binding'),plan)
                or type(closed.get('safe_to_resume')) is not bool):
            raise Refused('maintenance_close_not_proven')
        if len(session['events'])>=4 and closed['safe_to_resume'] is not True:
            raise Refused('maintenance_close_not_proven')
        gate=c.admission.gate if c.admission else WriteGateManager('/var/lib/dnf-gm/write-gate',owner=c.owner)
        released=next((e['data'] for e in session['events'] if e['phase']=='gate-released'),None)
        expected=released or raw['events'][1]['data']
        with gate.locked(False):
            if gate.read()!=expected:raise Refused('maintenance_restore_gate_changed')
        services=self.observe(plan,session)
        if any(s['state']=='changed' for s in services):
            result['reason']='maintenance_restore_unexpected_state';return result
        if (c._active()!=request_id or c._load(request_id)!=raw or load(c.root,c.owner,request_id,plan)!=session
                or _read(self.runtime,'closed.json',c.owner,MAX_CLOSE_BYTES)!=closed
                or os.path.lexists(self.runtime/'permit.json')):
            raise Refused('maintenance_restore_journal_changed')
        with gate.locked(False):
            if gate.read()!=expected:raise Refused('maintenance_restore_gate_changed')
        after,after_mono=c._now()
        if not (0<=after-closing['at']<duration and 0<=after_mono-closing['monotonic']<duration):
            result['reason']='maintenance_restore_observation_expired';return result
        if session['state']=='completed':
            # No maintenance exception after success; the ordinary collector
            # independently decides current service/gateway health.
            return {'active':False,'verified':False,'recorded_state':'completed'}
        return {**result,'verified':True,'services':services}
