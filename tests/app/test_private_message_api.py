import json
from pathlib import Path

import pytest

from dnfgm.native_monitor import MONITOR_SHA256

BASE = '/dnf-gm/api/v1/native-controls'
KEY = 'private-message-fixture-key'


@pytest.fixture
def message_control(env):
    client, settings, db, app = env
    settings.native_monitor_enabled = True
    settings.native_control_actions = ('native-message',)
    settings.write_approvals['native-message'] = True
    status = Path(settings.status_file)
    body = json.loads(status.read_text()); body['native_monitor_sha256'] = MONITOR_SHA256
    status.write_text(json.dumps(body))
    adapter = app.state.native_operations.private_message
    adapter.status = lambda: {'implemented': True, 'enabled': True, 'ready': True, 'bridge_state': 'ready', 'reason_code': None}
    calls = []
    def send(*args):
        assert db.slots._value == 3
        calls.append(args)
        return {'transport_status': 'sent', 'effect_status': 'unknown', 'reason_code': 'primitive_invoked', 'automatic_retry_allowed': False}
    adapter.send = send
    return client, settings, db, app, calls


def request(**changes):
    return {'action': 'native-message', 'uid': 900001, 'charac_no': 900001,
            'message': '请在城镇联系管理员', 'reason': 'fixture-system-message', **changes}


def test_message_preview_confirm_audit_no_replay(message_control):
    client, _, db, _, calls = message_control
    response = client.post(BASE + '/preview', json=request())
    assert response.status_code == 200, response.text
    result = response.json(); op = result['operation_id']
    assert result['preview']['target']['charac_no'] == 900001 and not calls
    confirmed = client.post(BASE + '/' + op + '/confirm', json={'idempotency_key': KEY})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()['result']['effect_status'] == 'unknown'
    assert calls == [(op, 900001, 900001, request()['message'])]
    again = client.post(BASE + '/' + op + '/confirm', json={'idempotency_key': KEY})
    assert again.json() == confirmed.json() and len(calls) == 1
    with db.connect() as c, c.cursor() as q:
        q.execute('SELECT operation_id FROM dnf_gm.audit ORDER BY id')
        assert [row['operation_id'] for row in q.fetchall()] == [op, 'native-result:' + op]
    assert client.get(BASE + '?uid=900001').json()['items'][0]['action'] == 'native-message'


@pytest.mark.parametrize('mutation', ['character', 'name', 'deleted', 'activation', 'bridge'])
def test_target_or_readiness_change_blocks_before_dispatch(message_control, mutation):
    client, settings, db, app, calls = message_control
    preview = client.post(BASE + '/preview', json=request()); assert preview.status_code == 200, preview.text
    op = preview.json()['operation_id']
    if mutation in ('character', 'name', 'deleted'):
        sql, value = {'character': ('m_id', 900002), 'name': ('charac_name', '已改名'), 'deleted': ('delete_flag', 1)}[mutation]
        with db.connect() as c, c.cursor() as q:
            q.execute('UPDATE taiwan_cain.charac_info SET ' + sql + '=%s WHERE charac_no=900001', (value,)); c.commit()
    elif mutation == 'activation':
        settings.native_control_actions = ()
    else:
        app.state.native_operations.private_message.status = lambda: {'ready': False}
    response = client.post(BASE + '/' + op + '/confirm', json={'idempotency_key': KEY})
    assert response.status_code == 409 and not calls
    assert client.get(BASE + '/' + op).json()['status'] == 'preview'


def test_message_character_ownership_and_disabled_status(message_control):
    client, settings, _, _, calls = message_control
    assert client.post(BASE + '/preview', json=request(charac_no=900002)).status_code == 409
    assert client.post(BASE + '/preview', json=request(charac_no=None)).status_code == 422
    assert client.get(BASE + '/status').json()['private_message']['ready'] is True
    settings.native_control_actions = ()
    assert client.post(BASE + '/preview', json=request()).status_code == 409 and not calls
