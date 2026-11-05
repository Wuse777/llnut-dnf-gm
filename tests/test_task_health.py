from types import SimpleNamespace
import pytest
from dnfgm.task_health import WorkerPulse, TaskHealth
from dnfgm.schedules import OperationsWorker


def test_pulse_failure_is_not_success_and_recovery_resets():
    now=[0.0]; p=WorkerPulse(lambda:now[0])
    assert p.snapshot('rewards',True,True)['state']=='observing'
    def fail():raise RuntimeError('private SQL must not escape')
    with pytest.raises(RuntimeError):p.call('rewards',fail)
    assert p.snapshot('rewards',True,True)=={'state':'failing','failures':1}
    assert p.call('rewards',lambda:False) is False
    assert p.snapshot('rewards',True,True)=={'state':'responding','failures':0}
    now[0]=121
    assert p.snapshot('rewards',True,True)['state']=='stalled'
    assert p.snapshot('rewards',False,True)['state']=='disabled'
    assert p.snapshot('rewards',True,False)['state']=='stopped'


def test_inflight_hang_has_own_age():
    now=[1];p=WorkerPulse(lambda:now[0])
    def step():
        now[0]=122
        assert p.snapshot('rewards',True,True)['state']=='stalled'
    p.call('rewards',step)
    assert p.snapshot('rewards',True,True)['state']=='responding'


def test_head_needs_continuous_observation_not_creation_age():
    now=[0];h=TaskHealth(None,None,None,clock=lambda:now[0])
    assert h.observe_head(('old',1))=='observing'
    now[0]=60;assert h.observe_head(('old',1))=='observing'
    now[0]=120;assert h.observe_head(('old',1))=='stalled'
    now[0]=121;assert h.observe_head(('old',2))=='advancing'
    now[0]=220;assert h.observe_head(('old',2))=='observing' # observation gap
    now[0]=240;assert h.observe_head(('next',2))=='observing'
    assert h.observe_head(None)=='idle'


def test_busy_and_database_failure_never_return_cached_clear():
    h=TaskHealth(None,None,None,wall=lambda:123)
    h.lock.acquire()
    try:assert h.read()=={'state':'unknown','checked_at':123,'reason':'busy','issues':[]}
    finally:h.lock.release()
    h.head=('old',1)
    assert h.read()['reason']=='query_failed'
    assert h.head is None


def test_schedule_failure_does_not_starve_rewards_or_disappear_from_pulse():
    calls=[]
    def bad():raise RuntimeError('sensitive')
    p=WorkerPulse()
    worker=OperationsWorker(SimpleNamespace(step=bad),SimpleNamespace(step=lambda:calls.append('reward')),
                            SimpleNamespace(schedule_worker_enabled=True,batch_worker_enabled=True),p)
    worker.step()
    assert calls==['reward']
    assert p.snapshot('schedules',True,True)['state']=='failing'
    assert p.snapshot('rewards',True,True)['state']=='responding'
