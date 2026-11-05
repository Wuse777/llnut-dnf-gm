"""One focused API contract test; no production maintenance commands."""
import json
from dnfgm.release_files import atomic_json
from test_maintenance_requests import setup, BASE
from test_maintenance_close import opened


def test_recovery_requires_fresh_confirmation_and_audits_one_attempt(opened):
    setup,op,fp=opened;c,s,db,app,w,coordinator,host,root=setup
    path=root/'results'/(op+'.json');state=json.loads(path.read_text())
    state.update(state='needs_review',recovery_available=True,revision=42)
    atomic_json(path,state)
    payload={'idempotency_key':'recover-fixture-0001','fingerprint':fp,'revision':42,'acknowledge_restore':True}
    assert c.get(BASE+'/requests/'+op).json()['can_recover']
    assert c.post(BASE+'/requests/'+op+'/recover',json={**payload,'acknowledge_restore':False}).status_code==422
    assert c.post(BASE+'/requests/'+op+'/recover',json={**payload,'revision':41}).status_code==409
    # Recovery is independent of the switch that controls NEW maintenance.
    s.write_approvals['maintenance']=False
    response=c.post(BASE+'/requests/'+op+'/recover',json=payload)
    assert response.status_code==200,response.text
    rid=response.json()['recovery_operation_id']
    assert c.post(BASE+'/requests/'+op+'/recover',json=payload).json()['recovery_operation_id']==rid
    with db.connect() as conn,conn.cursor() as q:
        q.execute("SELECT COUNT(*) AS n FROM dnf_gm.audit WHERE action='maintenance-recover'");assert q.fetchone()['n']==1
        q.execute('SELECT request_json FROM dnf_gm.operations WHERE operation_id=%s',(rid,));assert json.loads(q.fetchone()['request_json'])['revision']==42
    envelope=json.loads((root/'inbox'/(op+'.recover.json')).read_text())
    assert envelope['recovery_id']==rid and envelope['revision']==42
    assert not host.calls
    assert c.post(BASE+'/requests/'+op+'/recover',json={**payload,'revision':43}).status_code==409
