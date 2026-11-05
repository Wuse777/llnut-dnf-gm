import json
from pathlib import Path
import time
import pytest

P = '/dnf-gm/api/v1'


@pytest.mark.parametrize('state', ['healthy', 'unknown', 'stale', 'memory', 'swap', 'disk'])
def test_readiness_exposes_degraded_collector_without_breaking_health(env, state):
    client, settings, _, _ = env
    d = dict(collected_at=time.time(), core_ok=True, mem_available_mib=700,
             swap_free_mib=4000, disk_free_gib=10)
    if state == 'unknown': d['core_ok'] = False
    if state == 'stale': d['collected_at'] -= 60
    if state == 'memory': d['mem_available_mib'] = 255
    if state == 'swap': d['swap_free_mib'] = 1535
    if state == 'disk': d['disk_free_gib'] = 1.99
    Path(settings.status_file).write_text(json.dumps(d))
    assert client.get(P + '/health').status_code == 200
    result = client.get(P + '/ready')
    assert result.status_code == (200 if state == 'healthy' else 503)
    if state == 'healthy': assert result.json()['version'] == '0.3.1'


def test_health_requires_mail_ledger_migration(env):
    client,settings,db,app=env
    with db.connect() as c,c.cursor() as q:
        q.execute('DELETE FROM dnf_gm.schema_versions WHERE version>=4');c.commit()
    assert client.get(P+'/health').status_code==503


def test_health_requires_preferences_migration(env):
    client,settings,db,app=env
    with db.connect() as c,c.cursor() as q:
        q.execute('DELETE FROM dnf_gm.schema_versions WHERE version>=5');c.commit()
    response=client.get(P+'/health')
    assert response.status_code==503 and '012' in response.text


def test_health_requires_native_history_migration(env):
    client,settings,db,app=env
    with db.connect() as c,c.cursor() as q:
        q.execute('DELETE FROM dnf_gm.schema_versions WHERE version=7');c.commit()
    assert client.get(P+'/health').status_code==503


def test_health_requires_scheduling_migration(env):
    client,settings,db,app=env
    with db.connect() as c,c.cursor() as q:
        q.execute('DELETE FROM dnf_gm.schema_versions WHERE version=8');c.commit()
    assert client.get(P+'/health').status_code==503


def test_health_requires_inventory_snapshot_migration(env):
    client,settings,db,app=env
    with db.connect() as c,c.cursor() as q:
        q.execute('DELETE FROM dnf_gm.schema_versions WHERE version=9');c.commit()
    assert client.get(P+'/health').status_code==503


def test_health_requires_support_migration(env):
    client,settings,db,app=env
    with db.connect() as c,c.cursor() as q:
        q.execute('DELETE FROM dnf_gm.schema_versions WHERE version=10');c.commit()
    assert client.get(P+'/health').status_code==503


def test_health_requires_economy_projection(env):
    client,settings,db,app=env
    with db.connect() as c,c.cursor() as q:
        q.execute('DELETE FROM dnf_gm.schema_versions WHERE version=11');c.commit()
    assert client.get(P+'/health').status_code==503
