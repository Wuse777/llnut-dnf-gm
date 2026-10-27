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
    if state == 'healthy': assert result.json()['version'] == '0.2.0'
