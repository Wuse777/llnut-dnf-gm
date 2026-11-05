"""Crash/retry tests for the real journal with synthetic service commands only."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy'))
from maintenance_drain import DrainCoordinator, PREVIEW_TTL, Refused, digest
from dnfgm.release_files import atomic_json, maintenance_lock
from test_game_drain import FakeHost

RID = 'a' * 32
OTHER = 'b' * 32


@pytest.fixture
def rig(tmp_path):
    host = FakeHost()
    now = [1000.0, 50.0]
    broker = DrainCoordinator(tmp_path / 'journal', host, owner=os.geteuid(),
                              clock=lambda: now[0], monotonic=lambda: now[1])
    broker.initialize()
    return broker, host, now


def prepare(broker):
    return broker.prepare(RID, '测试维护')


def restart(broker):
    return DrainCoordinator(broker.root, broker.host, lock_path=broker.lock_path,
                            owner=os.geteuid(), clock=broker.clock, monotonic=broker.monotonic)


def signals(host):
    return [c for c in host.calls if '-2' in c]


def test_prepare_persisted_and_idempotent_without_any_mutation(rig):
    broker, host, _ = rig
    first = prepare(broker)
    assert first['state'] == 'prepared' and first['can_confirm']
    assert restart(broker).prepare(RID, ' 测试维护 ') == first
    assert not host.calls
    assert (broker.root / (RID + '.json')).stat().st_mode & 0o777 == 0o600
    assert broker.root.stat().st_mode & 0o777 == 0o700
    assert 'pid' not in json.dumps(first) and 'plan' not in first
    assert json.loads((broker.root / 'active.json').read_text()) == {'request_id': RID}


def test_complete_drain_has_ordered_durable_commands_not_a_maintenance_permit(rig):
    broker, host, _ = rig
    first = prepare(broker)
    seen = []
    run = host.command
    def command(args, timeout=10):
        disk = json.loads((broker.root / (RID + '.json')).read_text())
        phase = disk['events'][-1]['phase']
        expected = {'-O': 'inhibit-intent', 'touch': 'marker-intent', '-2': 'signal-intent'}
        for flag, stage in expected.items():
            if flag in args:
                assert phase == stage
                seen.append(stage)
        return run(args, timeout)
    host.command = command
    result = broker.confirm(RID, first['fingerprint'])
    assert seen == ['inhibit-intent', 'marker-intent', 'signal-intent']
    assert result['state'] == 'game_drained' and result['revision'] == 9
    assert result['maintenance_permit'] is False and result['can_resume'] is False
    assert result['command_may_have_run'] is True and result['client_verified'] is False
    calls = copy.deepcopy(host.calls)
    assert restart(broker).confirm(RID, first['fingerprint']) == result
    assert host.calls == calls
    with pytest.raises(Refused, match='other_request_active'):
        broker.prepare(OTHER, '不能覆盖尚未恢复的维护')
    with pytest.raises(Refused, match='unstarted_request'):
        broker.cancel(RID)


def test_idempotency_conflict_does_not_mutate_or_replace_plan(rig):
    broker, host, _ = rig
    first = prepare(broker)
    before = (broker.root / (RID + '.json')).read_bytes()
    with pytest.raises(Refused, match='request_conflict'):
        broker.prepare(RID, '不同原因')
    with pytest.raises(Refused, match='request_conflict'):
        broker.confirm(RID, '0' * 64)
    assert before == (broker.root / (RID + '.json')).read_bytes() and not host.calls


@pytest.mark.parametrize('value', ['', '../bad', 'A' * 32, 'a' * 33, 1, None, 'a' * 32 + '\n'])
def test_invalid_request_identifiers_rejected(rig, value):
    broker, host, _ = rig
    with pytest.raises(Refused, match='request_id_invalid'):
        broker.prepare(value, 'test')
    assert not host.calls


@pytest.mark.parametrize('value', ['', '  ', '长' * 201, None, 1])
def test_reason_required_but_not_interpreted_as_command(rig, value):
    broker, host, _ = rig
    with pytest.raises(Refused, match='reason_required'):
        broker.prepare(RID, value)
    assert not host.calls


def test_cancel_then_new_request_never_signals_old_request(rig):
    broker, host, _ = rig
    first = prepare(broker)
    cancelled = broker.cancel(RID)
    assert cancelled['state'] == 'cancelled'
    assert broker.cancel(RID) == cancelled
    newer = broker.prepare(OTHER, '下一次')
    assert newer['state'] == 'prepared'
    assert broker.confirm(RID, first['fingerprint'])['state'] == 'cancelled'
    assert not host.calls


@pytest.mark.parametrize('clock_index,delta', [(0, PREVIEW_TTL), (1, PREVIEW_TTL), (0, -1), (1, -1)])
def test_expiry_uses_wall_and_monotonic_time(rig, clock_index, delta):
    broker, host, now = rig
    first = prepare(broker)
    now[clock_index] += delta
    assert broker.confirm(RID, first['fingerprint'])['state'] == 'expired'
    broker.prepare(OTHER, '新申请')
    assert not host.calls


def test_coordinator_lock_serializes_start_cancel_and_plan_changes(rig):
    broker, host, _ = rig
    first = prepare(broker)
    with maintenance_lock(broker.lock_path):
        for action in [lambda: broker.confirm(RID, first['fingerprint']), lambda: broker.cancel(RID),
                       lambda: broker.prepare(OTHER, '并发申请')]:
            with pytest.raises(Refused, match='coordinator_busy'):
                action()
        # Status still works while executor holds global ownership.
        assert broker.status(RID) == first
    assert not host.calls


@pytest.mark.parametrize('phase', ['drain-started', 'inhibit-intent', 'inhibit-applied', 'marker-intent',
                                   'marker-applied', 'signal-intent', 'signal-sent', 'game-drained', 'drain-finished'])
@pytest.mark.parametrize('after_replace', [False, True])
def test_lost_persistence_at_every_phase_never_replays_commands(rig, phase, after_replace):
    broker, host, _ = rig
    first = prepare(broker)
    fault = [True]
    def writer(path, doc, mode):
        hit = path.name == RID + '.json' and doc.get('events') and doc['events'][-1]['phase'] == phase and fault[0]
        if hit and not after_replace:
            fault[0] = False
            raise OSError('private/path or secret must not be disclosed')
        atomic_json(path, doc, mode)
        if hit:
            fault[0] = False
            raise OSError('fsync response lost')
    broker.writer = writer
    result = broker.confirm(RID, first['fingerprint'])
    assert result['state'] == ('game_drained' if phase == 'drain-finished' and after_replace else 'needs_review')
    count = len(host.calls)
    resumed = restart(broker)
    assert resumed.confirm(RID, first['fingerprint']) == result
    assert len(host.calls) == count and len(signals(host)) <= 1
    assert 'private/path' not in json.dumps(result)
    assert resumed.status(RID)['maintenance_permit'] is False
    with pytest.raises(Refused, match='other_request_active'):
        resumed.prepare(OTHER, '另一个编号也不能绕过')


@pytest.mark.parametrize('stage', ['running', 'inhibit-intent', 'marker-intent', 'signal-intent', 'signal-sent'])
def test_hard_worker_death_has_no_automatic_replay_after_restart(rig, stage):
    broker, host, _ = rig
    first = prepare(broker)
    def writer(path, doc, mode):
        atomic_json(path, doc, mode)
        if (path.name == RID + '.json' and doc['state'] == 'running'
                and (not doc['events'] and stage == 'running'
                     or doc['events'] and doc['events'][-1]['phase'] == stage)):
            raise SystemExit('simulated process death')
    broker.writer = writer
    with pytest.raises(SystemExit):
        broker.confirm(RID, first['fingerprint'])
    count = len(host.calls)
    result = restart(broker).confirm(RID, first['fingerprint'])
    assert result['state'] == 'running' and not result['can_confirm']
    assert len(host.calls) == count


def test_ack_lost_after_signal_keeps_uncertain_outcome_and_readonly_observation(rig):
    broker, host, _ = rig
    first = prepare(broker)
    run = host.command
    def command(args, timeout=10):
        result = run(args, timeout)
        if '-2' in args:
            raise TimeoutError('ambiguous signal transport')
        return result
    host.command = command
    result = broker.confirm(RID, first['fingerprint'])
    assert result['state'] == 'needs_review' and result['phase'] == 'signal-intent'
    count = len(host.calls)
    observed = restart(broker).observe(RID)
    assert observed['state'] == 'observed' and observed['games'][0]['state'] == 'restart_inhibited'
    assert not observed['can_replay'] and not observed['can_resume']
    # The process can later exit, but observation cannot manufacture a sent/saved receipt.
    host.rows['game_siroco11'] = (False, False, False, True, -1)
    assert broker.observe(RID)['games'][0]['state'] == 'down_normal'
    assert broker.status(RID) == result
    assert len(host.calls) == count


@pytest.mark.parametrize('case', ['identity', 'mysql', 'pid', 'service_change', 'exception'])
def test_reconciliation_does_not_hide_changed_or_unknown_state(rig, case):
    broker, host, _ = rig
    prepare(broker)
    if case == 'identity':
        host.ident['boot_id'] = 'another-boot'
    elif case == 'mysql':
        host.rows['mysql'] = (True, True, True, False, 888)
    elif case == 'pid':
        host.process['start_ticks'] += 1
    elif case == 'service_change':
        original = host.services
        def services():
            result = original()
            host.rows['game_siroco11'] = (False, False, False, True, -1)
            return result
        host.services = services
    else:
        host.services = lambda: (_ for _ in ()).throw(OSError('secret details'))
    result = broker.observe(RID)
    assert result['state'] == ('observed' if case == 'pid' else 'unknown')
    if case == 'pid':
        assert result['games'][0]['state'] == 'changed'
    assert not host.calls and not result['maintenance_permit']
    assert 'secret details' not in json.dumps(result)


def test_cancelled_or_expired_request_cannot_overwrite_active_pointer(rig):
    broker, _, _ = rig
    prepare(broker)
    broker.cancel(RID)
    broker.prepare(OTHER, 'next')
    assert prepare(broker)['state'] == 'cancelled'
    assert json.loads((broker.root / 'active.json').read_text())['request_id'] == OTHER


@pytest.mark.parametrize('case', ['symlink', 'hardlink', 'writable', 'bad_hash', 'bad_chain', 'partial', 'invalid_phase'])
def test_untrusted_or_corrupt_journals_refuse_without_game_commands(rig, case, tmp_path):
    broker, host, _ = rig
    first = prepare(broker)
    path = broker.root / (RID + '.json')
    if case == 'symlink':
        data = path.read_text();path.unlink();other = tmp_path / 'other.json';other.write_text(data);path.symlink_to(other)
    elif case == 'hardlink':
        os.link(path, tmp_path / 'link.json')
    elif case == 'writable':
        path.chmod(0o666)
    elif case == 'partial':
        path.write_text('{')
    else:
        doc = json.loads(path.read_text())
        if case == 'bad_hash':
            doc['plan']['identity']['pid'] += 1
        elif case == 'bad_chain':
            doc['events'] = [{'sequence': 1, 'phase': 'drain-started', 'previous': 'bad', 'digest': 'bad'}]
        else:
            event = {'sequence': 1, 'phase': 'signal-intent', 'data': {'service': 'mysql'}, 'previous': doc['binding'], 'at': 1000}
            event['digest'] = digest(event)
            doc.update(state='running', events=[event])
        atomic_json(path, doc, mode=0o600)
    with pytest.raises((Refused, OSError, ValueError)):
        broker.confirm(RID, first['fingerprint'])
    assert not host.calls


def test_private_directory_and_stable_lock_contract(rig):
    broker, host, _ = rig
    ino = broker.lock_path.stat().st_ino
    broker.initialize()
    assert broker.lock_path.stat().st_ino == ino
    broker.root.chmod(0o755)
    with pytest.raises(Refused, match='not_private'):
        prepare(broker)
    assert not host.calls


def test_orphan_prepared_record_can_reclaim_missing_pointer_but_not_steal_another(rig):
    broker, host, _ = rig
    first = prepare(broker)
    (broker.root / 'active.json').unlink()
    assert prepare(broker) == first
    (broker.root / 'active.json').unlink()
    broker.prepare(OTHER, 'another')
    with pytest.raises(Refused, match='other_request_active'):
        broker.confirm(RID, first['fingerprint'])
    assert not host.calls


def test_changed_preview_is_recorded_without_any_commands_or_auto_new_plan(rig):
    broker, host, _ = rig
    first = prepare(broker)
    host.ident['pvf_sha256'] = 'f' * 64
    result = broker.confirm(RID, first['fingerprint'])
    assert result['state'] == 'needs_review' and result['error'] == 'maintenance_drain_preview_changed'
    assert not result['command_may_have_run'] and not host.calls


@pytest.mark.parametrize('flag,observed', [('-O', 'restart_inhibited_marker_missing'), ('touch', 'restart_inhibited')])
def test_inhibit_or_marker_transport_loss_is_observed_not_replayed(rig, flag, observed):
    broker, host, _ = rig
    first = prepare(broker)
    run = host.command
    def command(args, timeout=10):
        result = run(args, timeout)
        if flag in args:
            raise TimeoutError('response lost after command')
        return result
    host.command = command
    assert broker.confirm(RID, first['fingerprint'])['state'] == 'needs_review'
    count = len(host.calls)
    assert restart(broker).observe(RID)['games'][0]['state'] == observed
    restart(broker).confirm(RID, first['fingerprint'])
    assert len(host.calls) == count and not signals(host)


def test_status_marks_expired_preview_without_writing_or_claiming_completion(rig):
    broker, host, now = rig
    prepare(broker)
    path = broker.root / (RID + '.json')
    before = path.read_bytes()
    now[1] += PREVIEW_TTL
    state = broker.status(RID)
    assert state['state'] == 'prepared' and state['preview_expired'] and not state['can_confirm']
    assert state['can_cancel']
    assert before == path.read_bytes() and not host.calls


@pytest.mark.parametrize('field', ['created_at', 'created_monotonic', 'updated_at'])
@pytest.mark.parametrize('value', [True, None, '1000', -1])
def test_malformed_times_refuse_without_commands(rig, field, value):
    broker, host, _ = rig
    first = prepare(broker)
    path = broker.root / (RID + '.json')
    doc = json.loads(path.read_text())
    doc[field] = value
    doc['binding'] = digest({k: doc[k] for k in ('request_id', 'reason', 'plan', 'created_at', 'created_monotonic')})
    atomic_json(path, doc, mode=0o600)
    with pytest.raises(Refused, match='journal_invalid'):
        broker.confirm(RID, first['fingerprint'])
    assert not host.calls


def test_repeated_confirm_after_no_receipt_write_possible_still_never_replays(rig):
    broker, host, _ = rig
    first = prepare(broker)
    def writer(path, doc, mode):
        if doc.get('events') and doc['events'][-1]['phase'] == 'signal-sent' or doc.get('state') == 'needs_review':
            raise OSError('disk unavailable')
        atomic_json(path, doc, mode)
    broker.writer = writer
    with pytest.raises(OSError):
        broker.confirm(RID, first['fingerprint'])
    assert len(signals(host)) == 1
    count = len(host.calls)
    snapshot = restart(broker).confirm(RID, first['fingerprint'])
    assert snapshot['state'] == 'running' and snapshot['phase'] == 'signal-intent'
    assert len(host.calls) == count


def test_prepare_active_pointer_failure_can_only_be_recovered_for_the_same_plan(rig):
    broker, host, _ = rig
    def writer(path, doc, mode):
        if path.name == 'active.json':
            raise OSError('pointer write failed')
        atomic_json(path, doc, mode)
    broker.writer = writer
    with pytest.raises(OSError):
        prepare(broker)
    before = (broker.root / (RID + '.json')).read_bytes()
    recovered = prepare(restart(broker))
    assert recovered['state'] == 'prepared'
    assert before == (broker.root / (RID + '.json')).read_bytes()
    assert not host.calls


def test_no_active_game_never_sends_signal_or_claims_full_maintenance(rig):
    broker, host, _ = rig
    host.rows['game_siroco11'] = (False, False, False, True, -1)
    first = prepare(broker)
    result = broker.confirm(RID, first['fingerprint'])
    assert result['state'] == 'game_drained' and result['games'] == []
    assert not result['command_may_have_run'] and not result['maintenance_permit']
    assert not host.calls


from maintenance_drain import DrainMonitor
from monitor_runtime import protection_health


def interrupted(broker, host):
    first = prepare(broker)
    original = host.command
    def command(args, timeout=10):
        if '-2' in args:
            raise TimeoutError('signal outcome not recorded')
        return original(args, timeout)
    host.command = command
    assert broker.confirm(RID, first['fingerprint'])['state'] == 'needs_review'
    return first


def test_missing_prepared_cancelled_journals_do_not_create_monitor_exception(rig, tmp_path):
    broker, host, _ = rig
    missing = DrainCoordinator(tmp_path/'missing', host, owner=os.geteuid())
    assert DrainMonitor(missing).status() == {'active': False, 'verified': False}
    assert DrainMonitor(broker).status() == {'active': False, 'verified': False}
    prepare(broker)
    assert DrainMonitor(broker).status() == {'active': False, 'verified': False}
    broker.cancel(RID)
    assert DrainMonitor(broker).status() == {'active': False, 'verified': False}
    assert not host.calls


def test_verified_transition_keeps_only_gm_alive_and_never_claims_normal_game_health(rig):
    broker, host, now = rig
    interrupted(broker, host)
    count = len(host.calls)
    before = (broker.root / (RID+'.json')).read_bytes()
    status = DrainMonitor(broker).status()
    assert status['active'] and status['verified'] and status['authority'] == 'drain-transition'
    assert not status['maintenance_permit']
    collected = {'core_ok': False, 'maintenance': status}
    assert protection_health(collected, now[0])
    assert collected['core_ok'] is False
    assert count == len(host.calls) and before == (broker.root / (RID+'.json')).read_bytes()


@pytest.mark.parametrize('case', ['core_resource', 'changed_container', 'dependency', 'other_service',
                                  'abnormal_exit', 'restarted_game', 'elapsed_wall', 'elapsed_mono',
                                  'backward_wall', 'backward_mono', 'journal_corrupt'])
def test_transition_does_not_waive_real_failures_or_expire_silently(rig, case):
    broker, host, now = rig
    interrupted(broker, host)
    if case == 'core_resource':
        host.identity = lambda: (_ for _ in ()).throw(Refused('maintenance_resources_low'))
    elif case == 'changed_container':
        host.ident['container_id'] = 'f'*64
    elif case == 'dependency':
        host.rows['mysql'] = (True, True, True, False, 999)
    elif case == 'other_service':
        host.rows['mysql-log'] = (False, False, False, True, -1)
    elif case == 'abnormal_exit':
        host.rows['game_siroco11'] = (False, False, False, True, -1); host.exit = (0, 9)
    elif case == 'restarted_game':
        host.process['start_ticks'] += 1
    elif case == 'elapsed_wall':
        now[0] += 245
    elif case == 'elapsed_mono':
        now[1] += 245
    elif case == 'backward_wall':
        now[0] -= 1
    elif case == 'backward_mono':
        now[1] -= 1
    else:
        (broker.root / (RID+'.json')).write_text('{}')
    count = len(host.calls)
    status = DrainMonitor(restart(broker)).status()
    assert status['active'] and not status['verified']
    assert not protection_health({'core_ok': False, 'maintenance': status}, now[0])
    assert count == len(host.calls)


def test_monitor_does_not_renew_duration_after_worker_restart_or_refresh(rig):
    broker, host, now = rig
    interrupted(broker, host)
    first = DrainMonitor(broker).status()
    now[0] += 240; now[1] += 240
    second = DrainMonitor(restart(broker)).status()
    assert second['verified'] and first['expires_at'] == second['expires_at']
    now[0] += 5; now[1] += 5
    assert not DrainMonitor(restart(broker)).status()['verified']


def test_snapshot_changing_during_transition_check_is_not_reused(rig):
    broker, host, _ = rig
    interrupted(broker, host)
    original = broker.observe
    def observe(request_id):
        result = original(request_id)
        path = broker.root / (RID+'.json')
        doc = json.loads(path.read_text());doc['updated_at'] += 1
        atomic_json(path, doc, mode=0o600)
        return result
    broker.observe = observe
    result = DrainMonitor(broker).status()
    assert not result['verified'] and result['reason'] == 'maintenance_journal_changed'


def test_transition_expiring_during_probe_is_not_verified(rig):
    broker, host, now = rig
    interrupted(broker, host)
    original = broker.observe
    def observe(request_id):
        result = original(request_id)
        now[0] += 245; now[1] += 245
        return result
    broker.observe = observe
    result = DrainMonitor(broker).status()
    assert not result['verified'] and result['reason'] == 'maintenance_drain_observation_expired'


def test_live_dependency_or_unplanned_service_changes_before_confirmation_refuse(rig):
    broker, host, _ = rig
    first = prepare(broker)
    host.rows['mysql-log'] = (False, False, False, True, -1)
    result = broker.confirm(RID, first['fingerprint'])
    assert result['state'] == 'needs_review' and not host.calls


def test_existing_monitor_window_reads_transition_only_when_no_permit(rig, monkeypatch, tmp_path):
    import inventory_window
    import maintenance_drain
    import game_drain
    from types import SimpleNamespace
    broker, host, _ = rig
    interrupted(broker, host)
    monkeypatch.setattr(maintenance_drain, 'STATE', broker.root)
    monkeypatch.setattr(maintenance_drain, 'DrainCoordinator', lambda *a, **kw: broker)
    monkeypatch.setattr(game_drain, 'Host', lambda probe: host)
    adapter = object.__new__(inventory_window.MonitorWindow)
    root = tmp_path / 'runtime';root.mkdir()
    adapter.manager = SimpleNamespace(root=root, probe=None)
    adapter.monitored_components = ('mysql', 'game_siroco11')
    assert adapter.status()['authority'] == 'drain-transition'
    assert adapter.status()['verified']
    (root / 'permit.json').write_text('existing-fence')
    adapter.manager.refresh = lambda: None
    adapter.fence = SimpleNamespace(check=lambda: {'id': 'window', 'collected_at': 1000, 'expires_at': 1100})
    assert adapter.status() == {'active': True, 'verified': True, 'id': 'window', 'collected_at': 1000, 'expires_at': 1100}


def test_existing_transition_loading_failure_stays_unverified(rig, monkeypatch, tmp_path):
    import inventory_window
    import maintenance_drain
    import game_drain
    from types import SimpleNamespace
    broker, _, _ = rig
    monkeypatch.setattr(maintenance_drain, 'STATE', broker.root)
    monkeypatch.setattr(game_drain, 'Host', lambda probe: (_ for _ in ()).throw(RuntimeError('secret path')))
    adapter = object.__new__(inventory_window.MonitorWindow)
    adapter.manager = SimpleNamespace(root=tmp_path/'runtime', probe=None)
    assert adapter.status() == {'active': True, 'verified': False, 'reason': 'maintenance_transition_unavailable'}


@pytest.mark.parametrize('component', ['mysql-log', 'game_siroco11'])
def test_preexisting_core_component_failure_cannot_be_excused_as_drain(rig, component):
    broker, host, _ = rig
    host.rows[component] = (False, False, False, True, -1)
    first = prepare(broker)
    broker.confirm(RID, first['fingerprint'])
    status = DrainMonitor(broker, required_components=(component,)).status()
    assert status['active'] and not status['verified']
    assert status['reason'] == 'maintenance_preexisting_component_failure'


def test_transition_with_real_monitored_subset_checks_all_non_game_components(rig):
    broker, host, _ = rig
    interrupted(broker, host)
    status = DrainMonitor(broker, required_components=('mysql', 'game_siroco11', 'main_mysql_proxy')).status()
    assert status['verified']
    unknown = DrainMonitor(broker, required_components=('not-in-bound-plan',)).status()
    assert not unknown['verified']
