"""Actual isolated MySQL SQL, bounded inboxes and read-only API behavior."""
import time
from pathlib import Path

from test_combined_rewards import read, write

P = '/dnf-gm/api/v1'


def section(result, key):
    return next(item for item in result['sections'] if item['key'] == key)


def insert_operation(db, identifier, status, created_at):
    write(db, 'INSERT INTO dnf_gm.operations(operation_id,session_hash,fingerprint,action,request_json,'
          'preview_json,status,created_at,expires_at) VALUES(%s,%s,%s,\'reward\',\'{}\',\'{}\',%s,%s,%s)',
          (identifier, 'a'*64, 'b'*64, status, created_at, created_at + 300))


def test_workbench_original_states_newest_order_cap_and_read_only(env, monkeypatch):
    client, settings, db, app = env
    monkeypatch.setattr(app.state.maintenance, 'status', lambda: {'state': 'ok', 'write_gate': None})
    monkeypatch.setattr(app.state.task_health, 'read', lambda: {'state': 'clear', 'issues': []})
    for i in range(25):
        insert_operation(db, f'{i+1:032x}', ('uncertain', 'executing', 'dispatching')[i % 3], 100+i)
    insert_operation(db, 'f'*32, 'committed', 999)
    before = read(db, 'SELECT * FROM dnf_gm.operations ORDER BY operation_id')
    response = client.get(P+'/workbench')
    assert response.status_code == 200, response.text
    data = response.json(); inbox = section(data, 'operations')
    assert inbox['has_more'] and len(inbox['items']) == 20
    assert [item['created_at'] for item in inbox['items']] == list(range(124, 104, -1))
    for item in inbox['items']:
        original = next(row for row in before if row['operation_id'] == item['id'])
        assert item['query']['operation_id'] == original['operation_id'] and item['status'] == original['status']
    assert data['management_backup']['backup'] is None and data['read_only']
    assert read(db, 'SELECT * FROM dnf_gm.operations ORDER BY operation_id') == before
    assert not read(db, 'SELECT * FROM dnf_gm.audit')
    client.cookies.clear(); assert client.get(P+'/workbench').status_code == 401


def test_old_backup_exception_survives_more_than_twenty_new_successes(env, monkeypatch):
    client, settings, db, app = env
    monkeypatch.setattr(app.state.maintenance, 'status', lambda: {'state': 'ok', 'write_gate': {'state': 'open'}})
    monkeypatch.setattr(app.state.task_health, 'read', lambda: {'state': 'clear', 'issues': []})
    for i in range(23):
        write(db, 'INSERT INTO dnf_gm.game_backup_runs(run_id,backup_id,action,window_id,reason,state,'
            'fingerprint,spec_json,created_at,expires_at) VALUES(%s,%s,\'backup\',%s,\'fixture\',%s,%s,\'{}\',%s,%s)',
            (f'{i+1:032x}', f'{i+1:032x}', 'a'*32, 'needs_review' if i == 0 else 'succeeded', 'b'*64, i, i+300))
    response = client.get(P+'/workbench'); assert response.status_code == 200, response.text
    data = response.json()
    assert all(item['state'] == 'succeeded' for item in data['game_backup']['items'])
    old = next(item for item in section(data, 'infrastructure')['items'] if item['id'] == f'{1:032x}')
    assert old['status'] == 'needs_review' and old['query'] == {'run_id': f'{1:032x}'}


def test_workbench_support_batch_and_schedule_fields_match_actual_schema(env, monkeypatch):
    client, settings, db, app = env
    now = int(time.time())
    write(db, "INSERT INTO dnf_gm.support_cases(case_id,uid,charac_no,target_json,title,category,description,"
        "status,revision,created_at,updated_at) VALUES(%s,900001,NULL,'{}','角色问题','other','fixture','in_progress',1,%s,%s)",
        ('c'*32, now, now))
    write(db, "INSERT INTO dnf_gm.reward_jobs(id,session_hash,fingerprint,request_json,preview_json,status,reason,"
        "created_at,expires_at) VALUES(%s,%s,%s,'{}','{}','paused','批量fixture',%s,%s)", ('d'*32, 'a'*64, 'b'*64, now, now+300))
    write(db, "INSERT INTO dnf_gm.reward_targets(job_id,ordinal,target_uid,charac_no,target_json,operation_id,status,error_message) "
        "VALUES(%s,1,900001,900001,'{}',%s,'uncertain','按原编号核对')", ('d'*32, 'e'*32))
    write(db, "INSERT INTO dnf_gm.schedules(id,session_hash,fingerprint,title,kind,request_json,preview_json,status,"
        "next_due,created_at,expires_at,last_error) VALUES(%s,%s,%s,'今日补给','reward','{}','{}','paused',%s,%s,%s,'需核对')",
        ('f'*32, 'a'*64, 'b'*64, now-1, now, now+300))
    monkeypatch.setattr(app.state.task_health, 'read', lambda: {'state': 'clear', 'issues': []})
    response = client.get(P+'/workbench'); assert response.status_code == 200, response.text
    data = response.json()
    assert section(data, 'support')['items'][0]['query'] == {'uid': '900001', 'case_id': 'c'*32}
    assert section(data, 'batches')['items'][0]['query'] == {'job_id': 'd'*32, 'status': 'uncertain'}
    assert section(data, 'schedules')['items'][0]['query'] == {'schedule_id': 'f'*32}


def test_workbench_index_migration_repeats_and_preserves_outcome_index(env):
    db = env[2]
    insert_operation(db, 'a'*32, 'uncertain', 1)
    script = (Path(__file__).parents[2]/'migrations/020-workbench-index.sql').read_text()
    for _ in range(2):
        with db.connect() as c, c.cursor() as q:
            for statement in script.split(';'):
                if statement.strip(): q.execute(statement)
            c.commit()
    indexes = read(db, "SELECT INDEX_NAME,COLUMN_NAME FROM information_schema.STATISTICS WHERE TABLE_SCHEMA='dnf_gm' "
                       "AND TABLE_NAME='operations' AND INDEX_NAME IN ('workbench_created','outcome_status') ORDER BY INDEX_NAME,SEQ_IN_INDEX")
    assert [r['COLUMN_NAME'] for r in indexes if r['INDEX_NAME'] == 'workbench_created'] == ['status','created_at','operation_id']
    assert [r['COLUMN_NAME'] for r in indexes if r['INDEX_NAME'] == 'outcome_status'] == ['status','action','operation_id']
    item_index = read(db, "SELECT COLUMN_NAME FROM information_schema.STATISTICS WHERE TABLE_SCHEMA='dnf_gm' "
                         "AND TABLE_NAME='mail_deliveries' AND INDEX_NAME='operation_item' ORDER BY SEQ_IN_INDEX")
    assert [r['COLUMN_NAME'] for r in item_index] == ['operation_id','item_id']
    assert read(db, 'SELECT status FROM dnf_gm.operations')[0]['status'] == 'uncertain'
