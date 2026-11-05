"""Partial drains with synthetic s6 only; never operates production services."""
import copy
import pytest
from dnfgm.maintenance_requests import packet
from dnfgm.release_files import atomic_json
from test_service_lifecycle import rig, RID
from test_maintenance_executor import worker, send, receipt
from maintenance_session_monitor import SessionMonitor


def partial(worker, phase):
    w,c,h,_=worker;send(worker,'prepare');w.tick()
    writer=c.writer;once=[True]
    def fault(path,doc,mode):
        writer(path,doc,mode=mode)
        if path.name==RID+'.json' and doc.get('events') and doc['events'][-1]['phase']==phase and once[0]:
            once[0]=False;raise OSError('synthetic drain interruption')
    c.writer=fault;send(worker,'confirm');w.tick();c.writer=writer
    assert c._load(RID)['state']=='needs_review'
    # Real s6 -u does not replace an already-up process. Model that behavior.
    command=h.command
    def s6(args,timeout=10):
        name=args[-1].split('/')[-1]
        if args[3:5]==['s6-svc','-u'] and h.rows[name][0]:
            h.calls.append(list(args));row=list(h.rows[name]);row[1]=True;h.rows[name]=tuple(row);return
        return command(args,timeout)
    h.command=s6
    return w,c,h


def recover(worker,key="c"):
    w,c,h,_=worker;state=c.status(RID);assert state['recovery_available']
    value=packet(worker[3],'recover',fingerprint=state['fingerprint'],recovery={'recovery_id':key*32,'revision':state['revision']})
    path=w.root/'inbox'/(RID+'.recover.json');atomic_json(path,value,mode=0o600);w.tick()
    return value,path


@pytest.mark.parametrize('phase',['marker-applied','game-drained','writer-marker-applied'])
def test_partial_abort_preserves_live_processes_and_never_stops_more(worker,phase):
    w,c,h=partial(worker,phase)
    live={n:copy.deepcopy(h.processes[n]) for n,row in h.rows.items() if row[0]}
    before=copy.deepcopy(h.calls)
    proof=SessionMonitor(c,w.session.window.root).status();assert proof['verified'] and not proof['maintenance_permit']
    value,path=recover(worker)
    assert receipt(w)['state']=='completed',receipt(w)
    assert c._load(RID)['state']=='recovered'
    assert c.admission.gate.read()['state']=='open'
    assert not (w.session.window.root/'permit.json').exists()
    assert all(h.processes[n]==process for n,process in live.items())
    assert all(call[3:5] not in (['s6-svc','-2'],['s6-svc','-t'],['s6-svc','-O']) for call in h.calls[len(before):])
    after=copy.deepcopy(h.calls);atomic_json(path,value,mode=0o600);w.tick();assert h.calls==after
    assert SessionMonitor(c,w.session.window.root).status()['active'] is False


def test_live_process_with_exit_intent_remains_frozen_without_signal_replay(worker):
    w,c,h=partial(worker,'signal-intent');before=copy.deepcopy(h.calls)
    recover(worker)
    assert receipt(w)['state']=='needs_review'
    assert receipt(w)['error']=='maintenance_partial_exit_pending'
    assert c.admission.gate.read()['state']=='frozen' and h.calls==before


def test_partial_restoration_itself_can_resume_after_receipt_interruption(worker):
    w,c,h=partial(worker,'game-drained')
    writer=c.writer;once=[True]
    def fault(path,doc,mode):
        writer(path,doc,mode=mode)
        if path.name.startswith('session-') and doc.get('events') and doc['events'][-1]['phase']=='restore-marker-applied' and once[0]:
            once[0]=False;raise OSError('synthetic partial restoration interruption')
    c.writer=fault;recover(worker);c.writer=writer
    assert receipt(w)['state']=='needs_review'
    assert SessionMonitor(c,w.session.window.root).status()['verified']
    recover(worker,key='b')
    assert receipt(w)['state']=='completed',receipt(w)
    starts=[tuple(call) for call in h.calls if call[3:5]==['s6-svc','-u']]
    assert len(starts)==len(set(starts))
