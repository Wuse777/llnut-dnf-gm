import json,time
import pytest
from dnfgm.native_monitor import MONITOR_SHA256

P='/dnf-gm/api/v1'


def test_live_query_default_disabled_and_no_sensitive_fields(env,monkeypatch):
    c,s,db,app=env
    monkeypatch.setattr(app.state.native_monitor,'socket_factory',lambda *a:pytest.fail('disabled network'))
    r=c.get(P+'/online/900001/live')
    assert r.status_code==200,r.text
    d=r.json();assert d['native']['state']=='unknown' and d['native']['reason_code']=='disabled'
    assert d['database']['record']=={'login_status':1,'channel':3011}
    assert 'password' not in r.text and 'db_host' not in r.text and 'fixture-only' not in r.text


def test_live_query_releases_db_slot_before_network_and_preserves_divergence(env,monkeypatch):
    c,s,db,app=env
    calls=[]
    def query(uid):
        # All three pool slots are available (auth and read connections returned).
        held=[]
        try:
            for _ in range(3):
                assert db.slots.acquire(blocking=False);held.append(1)
        finally:
            for _ in held:db.slots.release()
        calls.append(uid)
        return {'uid':uid,'source':'native_monitor','state':'offline','observed_at':time.time()}
    monkeypatch.setattr(app.state.native_monitor,'query',query)
    r=c.get(P+'/online/900001/live');assert r.status_code==200,r.text
    assert r.json()['native']['state']=='offline' and r.json()['database']['record']['login_status']==1
    assert calls==[900001]
    with db.connect() as con,con.cursor() as q:
        q.execute('SELECT login_status FROM taiwan_login.login_account_3 WHERE m_id=900001')
        assert q.fetchone()['login_status']==1 # not "repairing" a session using SQL
        q.execute('SELECT COUNT(*) n FROM dnf_gm.audit')
        assert q.fetchone()['n']==0


def test_live_requires_auth_known_account_and_integer_uid(env,monkeypatch):
    c,s,db,app=env
    monkeypatch.setattr(app.state.native_monitor,'query',lambda *a:pytest.fail('must not query'))
    assert c.get(P+'/online/123/live').status_code==404
    for uid in ('0','-1','4294967296','x','1%20OR%201=1'):
        assert c.get(P+'/online/'+uid+'/live').status_code==422
    c.cookies.clear()
    assert c.get(P+'/online/900001/live').status_code==401


def test_live_queries_are_rate_limited(env):
    c,s,db,app=env
    for _ in range(12):assert c.get(P+'/online/900001/live').status_code==200
    assert c.get(P+'/online/900001/live').status_code==429
    # Query budget is separate from ordinary account browsing.
    assert c.get(P+'/accounts').status_code==200
