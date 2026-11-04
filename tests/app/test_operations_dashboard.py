"""Authenticated diagnostic endpoint over synthetic monitor data."""
import json
from pathlib import Path
import sys
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'deploy'))
from telemetry import Recorder
def status():return dict(cpu_percent=20,mem_available_mib=600,mem_total_mib=1600,swap_free_mib=3000,swap_total_mib=6000,disk_free_gib=10,disk_total_gib=40,core_ok=True)

P='/dnf-gm/api/v1'


def test_operations_dashboard_readonly_auth_schema_and_no_path_override(env,tmp_path):
    client,s,db,app=env;s.telemetry_file=str(tmp_path/'history.sqlite')
    with db.connect() as c,c.cursor() as q:
        q.execute('SELECT COUNT(*) n FROM dnf_gm.audit');before=q.fetchone()['n']
    r=Recorder(s.telemetry_file,releases=str(tmp_path/'missing'),current=str(tmp_path/'c'),previous=str(tmp_path/'p'),protection=str(tmp_path/'protection'))
    try:
        r.observe(status());r.record_event('protection_stop',{'reason':'resource_failure','password':'must-not-leak'})
        d=client.get(P+'/operations-dashboard?window=7d&filename=/etc/shadow');assert d.status_code==200,d.text
        payload=d.json();assert payload['fresh'] and payload['current']['fresh']
        assert payload['application']['schema_versions'][0]['version']==7
        assert payload['events'][0]['details']=={'reason':'resource_failure'}
        assert '/etc/shadow' not in d.text and 'must-not-leak' not in d.text
        assert client.post(P+'/operations-dashboard',json={'command':'restart docker'}).status_code==405
        assert client.get(P+'/operations-dashboard?window=1year').status_code==422
        assert client.get(P+'/operations-dashboard?before=-1').status_code==422
        with TestClient(app) as anonymous:
            assert anonymous.get(P+'/operations-dashboard').status_code==401
        with db.connect() as c,c.cursor() as q:
            q.execute('SELECT COUNT(*) n FROM dnf_gm.audit');assert q.fetchone()['n']==before
    finally:r.close()


def test_history_unavailable_does_not_fabricate_current_or_history(env,tmp_path):
    client,s,_,_=env;s.telemetry_file=str(tmp_path/'absent')
    d=client.get(P+'/operations-dashboard').json();assert d['state']=='unavailable' and d['points']==[]
    assert d['current']['fresh']  # independent live status remains legitimate
    p=Path(s.status_file);state=json.loads(p.read_text());state['collected_at']=1;p.write_text(json.dumps(state))
    d=client.get(P+'/operations-dashboard').json()
    assert not d['current']['fresh'] and d['current']['mem_available_mib'] is None and d['current']['core_ok'] is None
