import json
import uuid
from test_mail_gold import P,preview,confirm


def test_export_has_snapshot_metadata_all_pages_filter_and_completion(env):
    c,s,db,app=env
    with db.connect() as con,con.cursor() as q:
        q.executemany('INSERT INTO dnf_gm.audit(operation_id,actor,action,target_uid,reason,request_json,result_json) VALUES(%s,\'owner\',\'fixture\',%s,%s,\'{}\',\'{}\')',[(uuid.uuid4().hex,900001 if n%2 else 900002,'=untrusted text') for n in range(205)])
        con.commit()
    r=c.get(P+'/audit/export?uid=900001');assert r.status_code==200,r.text
    lines=[json.loads(x) for x in r.text.splitlines()]
    assert lines[0]['type']=='metadata' and lines[-1]['type']=='complete'
    assert lines[-1]['records']==102
    assert len(lines)==104 and all(x['target_uid']==900001 for x in lines[1:-1])
    assert lines[1]['reason']=='=untrusted text'  # JSON, not executable CSV formula
    assert 'attachment' in r.headers['content-disposition']
    c.cookies.clear();assert c.get(P+'/audit/export').status_code==401


def test_operation_links_failed_attempt_without_claiming_final_failure(env):
    c,s,db,app=env
    op=preview(c).json()['operation_id']
    with db.connect() as con,con.cursor() as q:
        q.execute('INSERT INTO dnf_gm.failures(operation_id,error_type) VALUES(%s,\'OperationalError\')',(op,));con.commit()
    data=c.get(P+'/operations/'+op).json()
    assert data['status']=='preview' and data['request']['uid']==900001
    assert data['failure_attempts'][0]['error_type']=='OperationalError'
    assert '不代表' in data['failure_note']
    assert confirm(c,op).status_code==200
    data=c.get(P+'/operations/'+op).json()
    assert data['status']=='committed' and len(data['failure_attempts'])==1
