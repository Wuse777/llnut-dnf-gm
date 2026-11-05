"""Targeted interrupted restore checks; synthetic services, no production writes."""
import copy
import os
import pytest
from dnfgm.release_files import atomic_json
from dnfgm.maintenance_requests import packet
from test_service_lifecycle import rig, RID
from test_maintenance_executor import worker, enter, send, receipt
from maintenance_session_monitor import SessionMonitor


def interrupt(worker, phase, *, before=False):
    w,c,h,_=worker;enter(worker);original=c.writer;once=[True]
    def write(path,doc,mode):
        hit=path.name.startswith('session-') and doc.get('events') and doc['events'][-1]['phase']==phase and once[0]
        if hit:once[0]=False
        if hit and before:raise OSError('synthetic interrupted receipt before save')
        original(path,doc,mode=mode)
        if hit:raise OSError('synthetic interrupted receipt after save')
    c.writer=write;send(worker,'close');w.tick();c.writer=original
    assert receipt(w)['state']=='needs_review'
    return w,c,h


@pytest.mark.parametrize('phase,before', [('restore-marker-applied',False),('restore-start-sent',True),('gate-released',True)])
def test_explicit_recovery_resumes_and_duplicate_attempt_never_replays(worker,phase,before):
    w,c,h=interrupt(worker,phase,before=before)
    original=copy.deepcopy(h.calls)
    # A repeated original close is query-only; new explicit recovery is needed.
    send(worker,'close');w.tick();assert h.calls==original
    state=receipt(w);assert state['recovery_available']
    proof=SessionMonitor(c,w.session.window.root).status()
    assert proof['verified'] and proof['authority']=='recovery-only' and proof['maintenance_permit'] is False
    value=packet(worker[3],'recover',fingerprint=state['fingerprint'],
        recovery={'recovery_id':'e'*32,'revision':state['revision']})
    path=w.root/'inbox'/(RID+'.recover.json');atomic_json(path,value,mode=0o600)
    assert w.tick()['processed']==1
    assert receipt(w)['state']=='completed',receipt(w)
    starts=[tuple(x) for x in h.calls if 's6-svc' in x and '-u' in x]
    assert len(starts)==len(set(starts))
    after=copy.deepcopy(h.calls);atomic_json(path,value,mode=0o600);w.tick();assert h.calls==after
    assert c.admission.gate.read()['state']=='open'


def test_unproven_start_is_not_replayed(worker):
    w,c,h=interrupt(worker,'restore-start-intent');before=copy.deepcopy(h.calls)
    state=receipt(w)
    value=packet(worker[3],'recover',fingerprint=state['fingerprint'],
        recovery={'recovery_id':'f'*32,'revision':state['revision']})
    atomic_json(w.root/'inbox'/(RID+'.recover.json'),value,mode=0o600);w.tick()
    assert receipt(w)['error']=='maintenance_start_outcome_unproven'
    assert h.calls==before and c.admission.gate.read()['state']=='frozen'
