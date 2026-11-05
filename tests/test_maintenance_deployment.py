"""Deployment/rollback must not strand a durable game maintenance request."""
import os
from pathlib import Path
import sys

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy'))
from check_maintenance_idle import assert_idle
from maintenance_drain import DrainCoordinator, Refused
from maintenance_fixtures import admission
from dnfgm.release_files import atomic_json
from test_game_drain import FakeHost


@pytest.fixture
def rig(tmp_path):
    state, runtime = tmp_path / 'private', tmp_path / 'runtime'
    host = FakeHost()
    coordinator = DrainCoordinator(state, host, owner=os.geteuid(), admission=admission(tmp_path))
    def check():
        return assert_idle(state=state, runtime=runtime, owner=os.geteuid())
    return coordinator, runtime, host, check


def test_not_installed_or_empty_journal_does_not_block_deploy(rig):
    c, _, h, check = rig
    check();c.initialize();check()
    assert not h.calls


@pytest.mark.parametrize('state', ['prepared', 'running', 'needs_review', 'game_drained'])
def test_unfinished_request_blocks_before_service_mutations(rig, state):
    c, _, h, check = rig
    c.initialize();p = c.prepare('a'*32, '维护')
    if state == 'game_drained':
        c.confirm(p['request_id'], p['fingerprint'])
    elif state == 'needs_review':
        h.ident['boot_id'] = 'new-boot'
        c.confirm(p['request_id'], p['fingerprint'])
    elif state == 'running':
        original = c.writer
        def writer(path, doc, mode):
            original(path, doc, mode=mode)
            if doc.get('state') == 'running':
                raise SystemExit()
        c.writer = writer
        with pytest.raises(SystemExit):
            c.confirm(p['request_id'], p['fingerprint'])
    before = list(h.calls)
    with pytest.raises(Refused, match='request_not_finished'):
        check()
    assert h.calls == before


def test_unstarted_cancelled_request_allows_deploy_without_deleting_receipts(rig):
    c, _, h, check = rig
    c.initialize();c.prepare('a'*32, '维护');c.cancel('a'*32)
    before = (c.root/('a'*32+'.json')).read_bytes()
    check()
    assert (c.root/('a'*32+'.json')).read_bytes() == before and not h.calls


@pytest.mark.parametrize('case', ['permit', 'closed_unknown', 'closed_false', 'bad_json'])
def test_existing_window_requires_explicit_successful_close(rig, case):
    c, runtime, h, check = rig
    runtime.mkdir(mode=0o755)
    if case == 'permit':
        (runtime/'permit.json').write_text('expired-or-invalid')
    else:
        atomic_json(runtime/'closed.json', {'safe_to_resume': case == 'closed_true'})
        if case == 'closed_unknown':
            atomic_json(runtime/'closed.json', {'id': 'a'*32})
        if case == 'bad_json':
            (runtime/'closed.json').write_text('{')
    with pytest.raises((Refused, ValueError)):
        check()
    assert not h.calls


def test_closed_and_reconciled_window_alone_does_not_block(rig):
    _, runtime, h, check = rig
    runtime.mkdir(mode=0o755);atomic_json(runtime/'closed.json', {'safe_to_resume': True})
    check();assert not h.calls


def test_pointer_missing_next_to_request_is_not_treated_as_idle(rig):
    c, _, h, check = rig
    c.initialize();c.prepare('a'*32, '维护');(c.root/'active.json').unlink()
    with pytest.raises(Refused, match='journal_unresolved'):
        check()
    assert not h.calls


def test_guard_runs_with_shared_lock_before_any_restart_or_switch():
    root = Path(__file__).resolve().parents[1]
    for file in ('install.sh', 'rollback.sh'):
        text = (root/'deploy'/file).read_text()
        assert text.index('flock -x 9') < text.index('check_maintenance_idle.py') < text.index('systemctl stop')
        assert text.index('check_maintenance_idle.py') < text.index('no-auto-recover')
    text = (root/'deploy/install.sh').read_text()
    assert text.index('sha256sum --check') < text.index('check_maintenance_idle.py') < text.index('ln -sfn')
