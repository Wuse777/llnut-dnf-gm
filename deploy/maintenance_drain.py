"""Durable root-only coordinator for the fixed game drain phase.

This is NOT a generic service controller or a complete maintenance worker. No
CLI, socket, web route, service installation or automatic recovery is exposed.
A future authenticated outbox worker supplies only request id/reason; this class
creates the actual plan locally. Closing the browser or restarting the worker
must never replay a command. New plans bind the original database UUID and
require persistent admission freeze / transaction drain before game commands.
Outcome reconciliation, remaining writers, close and resume are still separate
phases; game_drained deliberately retains ownership and the frozen gate.
"""
from contextlib import contextmanager
import copy
import hashlib
import math
import os
from pathlib import Path
import re
import time

from dnfgm.inventory_fence import _read, directory
from dnfgm.release_files import Refused, atomic_json, canonical, maintenance_lock, OP, HEX
from game_drain import GameDrain, TIMEOUT
from maintenance_admission import validate_plan as validate_admission_plan
from maintenance_gate import binding_hash, WriteGateManager
from service_lifecycle import validate_cycle, stop_steps, ServiceLifecycle, STOP_TIMEOUT

STATE = Path('/var/lib/dnf-gm/maintenance-drain')
GLOBAL_LOCK = Path('/var/lib/dnf-gm/maintenance.lock')
PREVIEW_TTL = 300
MAX_BYTES = 256 * 1024
STATES = {'prepared', 'running', 'needs_review', 'game_drained', 'writers_stopped', 'cancelled', 'expired'}
TERMINAL_NO_EFFECT = {'cancelled', 'expired'}
COMMAND_INTENTS = {'inhibit-intent', 'marker-intent', 'signal-intent', 'writer-inhibit-intent', 'writer-marker-intent', 'writer-signal-intent'}


def error_code(error):
    # Never publish subprocess output, local paths, credentials or tracebacks.
    text = str(error)
    if isinstance(error, Refused) and re.fullmatch(r'maintenance_[a-z_]{1,100}', text):
        return text
    return 'maintenance_executor_failed'


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


class DrainCoordinator:
    def __init__(self, root, host, *, lock_path=None, owner=0,
                 clock=time.time, monotonic=time.monotonic, writer=atomic_json, admission=None, lifecycle=None):
        self.root = Path(root)
        self.admission = admission
        self.lifecycle = lifecycle
        self.host = host
        self.owner = owner
        self.clock, self.monotonic, self.writer = clock, monotonic, writer
        self.lock_path = Path(lock_path) if lock_path is not None else self.root / 'coordinator.lock'

    def initialize(self):
        directory(self.root.parent, self.owner)
        try:
            self.root.mkdir(mode=0o700)
        except FileExistsError:
            pass
        self._directory()
        parent_fd = os.open(self.root.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        # Do not replace the lock inode, including on worker restart.
        with self.locked():
            pass

    def _directory(self):
        directory(self.root, self.owner)
        if self.root.stat().st_mode & 0o077:
            raise Refused('maintenance_journal_not_private')
        directory(self.lock_path.parent, self.owner)

    @contextmanager
    def locked(self):
        self._directory()
        try:
            with maintenance_lock(self.lock_path):
                yield
        except BlockingIOError:
            raise Refused('maintenance_coordinator_busy') from None

    def _now(self):
        values = self.clock(), self.monotonic()
        if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in values):
            raise Refused('maintenance_clock_invalid')
        return values

    @staticmethod
    def _id(request_id):
        if not isinstance(request_id, str) or not OP.fullmatch(request_id):
            raise Refused('maintenance_request_id_invalid')
        return request_id

    @staticmethod
    def _reason(reason):
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 200:
            raise Refused('maintenance_reason_required')
        return reason.strip()

    def _write(self, name, value):
        self._directory()
        if len(canonical(value)) > MAX_BYTES:
            raise Refused('maintenance_journal_budget')
        self.writer(self.root / name, value, mode=0o600)

    def _active(self):
        try:
            value = _read(self.root, 'active.json', self.owner, 4096)
        except FileNotFoundError:
            return None
        if not isinstance(value, dict) or set(value) != {'request_id'}:
            raise Refused('maintenance_journal_invalid')
        return self._id(value['request_id'])

    def _claim(self, request_id):
        current = self._active()
        if current == request_id:
            return
        if current is not None:
            prior = self._load(current)
            if prior['state'] not in TERMINAL_NO_EFFECT:
                raise Refused('maintenance_other_request_active')
        self._write('active.json', {'request_id': request_id})

    def _load(self, request_id):
        self._id(request_id)
        doc = _read(self.root, request_id + '.json', self.owner, MAX_BYTES)
        try:
            if (not isinstance(doc, dict) or type(doc['version']) is not int or doc['version'] not in (1, 2, 3) or doc['request_id'] != request_id
                    or doc['state'] not in STATES or doc['reason'] != self._reason(doc['reason'])
                    or not isinstance(doc['events'], list) or len(doc['events']) > 512):
                raise ValueError()
            for field in ('created_at', 'created_monotonic', 'updated_at'):
                value = doc[field]
                if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                    raise ValueError()
            if doc['state'] in {'running', 'needs_review', 'game_drained', 'writers_stopped'}:
                for field in ('started_at', 'started_monotonic'):
                    value = doc[field]
                    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                        raise ValueError()
            if doc['version'] >= 2:
                validate_admission_plan(doc['plan']['admission'])
            elif 'admission' in doc['plan']:
                raise ValueError()
            if doc['version'] == 3:
                validate_cycle(doc['plan'])
                if doc['state']=='game_drained':raise ValueError()
            elif 'service_cycle' in doc['plan'] or doc['state']=='writers_stopped':
                raise ValueError()
            plan = copy.deepcopy(doc['plan'])
            fingerprint = plan.pop('fingerprint')
            if not HEX.fullmatch(fingerprint) or digest(plan) != fingerprint:
                raise ValueError()
            binding = {k: doc[k] for k in ('request_id', 'reason', 'plan', 'created_at', 'created_monotonic')}
            if doc['binding'] != digest(binding):
                raise ValueError()
            for i, event in enumerate(doc['events']):
                if (not isinstance(event, dict) or type(event['at']) not in (int, float)
                        or not math.isfinite(event['at']) or event['at'] < 0 or type(event['sequence']) is not int
                        or event['sequence'] != i + 1
                        or event['previous'] != (doc['binding'] if i == 0 else doc['events'][i - 1]['digest'])
                        or event['digest'] != digest({k: v for k, v in event.items() if k != 'digest'})):
                    raise ValueError()
            # A command history must be an exact prefix of this locally prepared plan.
            expected = self._steps(doc['plan'], doc['request_id'])
            if len(doc['events']) > len(expected):
                raise ValueError()
            for event, (phase, payload) in zip(doc['events'], expected):
                if event['phase'] != phase or not self._payload_equal(phase, event['data'], payload):
                    raise ValueError()
            if doc['state'] in {'prepared', *TERMINAL_NO_EFFECT} and doc['events']:
                raise ValueError()
            if doc['state'] in ('game_drained','writers_stopped') and len(doc['events']) != len(expected):
                raise ValueError()
            return doc
        except (KeyError, TypeError, ValueError, AttributeError):
            raise Refused('maintenance_journal_invalid') from None

    @staticmethod
    def _steps(plan, request_id=None):
        steps = []
        if 'admission' in plan:
            a = validate_admission_plan(plan['admission'])
            token = {'version': 1, 'state': 'frozen', 'generation': a['gate']['generation'] + 1,
                     'operation_id': request_id, 'binding_sha256': binding_hash(plan['identity'])}
            proof = {'protocol_version': 1, 'ordinary_transactions_drained': True,
                     'operation_id': request_id, 'generation': token['generation'],
                     'binding_sha256': token['binding_sha256'], 'server_uuid': a['server_uuid'],
                     'game_writes': False, 'maintenance_permit': False}
            steps.extend([('freeze-intent', {'server_uuid': a['server_uuid'], 'open_generation': a['gate']['generation']}),
                          ('write-gate-frozen', token), ('database-drained', proof)])
        steps.append(('drain-started', {'fingerprint': plan['fingerprint']}))
        for game in plan['games']:
            service = {'service': game['service']}
            steps.extend((phase, service) for phase in ('inhibit-intent', 'inhibit-applied', 'marker-intent', 'marker-applied'))
            steps.extend([('signal-intent', {**service, 'signal': 'SIGUSR2'}),
                          ('signal-sent', service), ('game-drained', service)])
        steps.append(('drain-finished', {'state': 'game_drained', 'fingerprint': plan['fingerprint'],
                      'services': [g['service'] for g in plan['games']],
                      'maintenance_permit': False, 'client_verified': False}))
        if 'service_cycle' in plan:steps.extend(stop_steps(plan))
        return steps

    @staticmethod
    def _payload_equal(phase, data, expected):
        if phase in ('write-gate-frozen', 'database-drained'):
            time_field = 'changed_at' if phase == 'write-gate-frozen' else 'checked_at'
            return (isinstance(data, dict) and set(data) == set(expected) | {time_field}
                    and all(type(data[k]) is type(v) and data[k] == v for k, v in expected.items())
                    and type(data[time_field]) in (int, float) and math.isfinite(data[time_field]) and data[time_field] >= 0)
        if phase == 'writer-stopped':
            return (isinstance(data,dict) and set(data)=={'service','exit_code','signum'}
                    and data['service']==expected['service'] and type(data['exit_code']) is int and type(data['signum']) is int
                    and (data['exit_code']==0 and data['signum'] in (0,-1)
                         or expected['signal']=='SIGTERM' and data['exit_code']==256 and data['signum']==15))
        if phase == 'game-drained':
            return (isinstance(data, dict) and set(data) == {'service', 'exit_code', 'signum'}
                    and data['service'] == expected['service'] and type(data['exit_code']) is int
                    and data['exit_code'] == 0 and type(data['signum']) is int and data['signum'] in (0, -1))
        return data == expected

    def view(self, doc):
        events = doc['events']
        now, mono = self._now()
        current = 0 <= now - doc['created_at'] < PREVIEW_TTL and 0 <= mono - doc['created_monotonic'] < PREVIEW_TTL
        return {'request_id': doc['request_id'], 'state': doc['state'], 'reason': doc['reason'],
                'fingerprint': doc['plan']['fingerprint'], 'created_at': doc['created_at'],
                'expires_at': doc['created_at'] + PREVIEW_TTL,
                'updated_at': doc['updated_at'], 'revision': len(events),
                'phase': events[-1]['phase'] if events else None,
                'games': [g['service'] for g in doc['plan']['games']],
                'events': [{'sequence': e['sequence'], 'phase': e['phase'], 'at': e['at'],
                            'service': e['data'].get('service')} for e in events],
                'command_may_have_run': any(e['phase'] in COMMAND_INTENTS for e in events),
                'error': doc.get('error'), 'maintenance_permit': False,
                'can_confirm': doc['version'] >= 2 and doc['state'] == 'prepared' and current,
                'preview_expired': doc['state'] == 'prepared' and not current,
                'can_cancel': doc['state'] == 'prepared', 'can_replay': False,
                'can_resume': False, 'client_verified': False}

    def prepare(self, request_id, reason):
        request_id, reason = self._id(request_id), self._reason(reason)
        with self.locked():
            try:
                old = self._load(request_id)
            except FileNotFoundError:
                old = None
            if old is not None:
                if old['reason'] != reason:
                    raise Refused('maintenance_request_conflict')
                if old['state'] not in TERMINAL_NO_EFFECT:
                    self._claim(request_id)
                return self.view(old)
            # Refuse before probing or creating another pending plan.
            active = self._active()
            if active and self._load(active)['state'] not in TERMINAL_NO_EFFECT:
                raise Refused('maintenance_other_request_active')
            if self.admission is None:
                raise Refused('maintenance_admission_required')
            admission_plan = self.admission.prepare()
            validate_admission_plan(admission_plan)
            plan = GameDrain(self.host).prepare()
            binding_hash(plan['identity'])
            if self.lifecycle is not None:
                if self.lifecycle.host is not self.host:raise Refused('maintenance_service_host_mismatch')
                plan['service_cycle']=self.lifecycle.prepare(plan)
                validate_cycle(plan)
            self.admission.verify_plan(admission_plan)
            plan.pop('fingerprint')
            plan['admission'] = admission_plan
            plan['fingerprint'] = digest(plan)
            now, mono = self._now()
            doc = {'version': 3 if self.lifecycle is not None else 2, 'request_id': request_id, 'reason': reason, 'plan': plan,
                   'created_at': now, 'created_monotonic': mono, 'updated_at': now,
                   'state': 'prepared', 'events': []}
            doc['binding'] = digest({k: doc[k] for k in ('request_id', 'reason', 'plan', 'created_at', 'created_monotonic')})
            self._write(request_id + '.json', doc)
            self._claim(request_id)
            return self.view(doc)

    def status(self, request_id):
        # Atomic snapshot reads are available even while the executor holds its lock.
        return self.view(self._load(request_id))

    def cancel(self, request_id):
        with self.locked():
            doc = self._load(request_id)
            if doc['state'] in TERMINAL_NO_EFFECT:
                return self.view(doc)
            if doc['state'] != 'prepared':
                raise Refused('maintenance_cancel_requires_unstarted_request')
            doc.update(state='cancelled', updated_at=self._now()[0])
            self._write(request_id + '.json', doc)
            return self.view(doc)

    def confirm(self, request_id, fingerprint):
        if not isinstance(fingerprint, str) or not HEX.fullmatch(fingerprint):
            raise Refused('maintenance_fingerprint_invalid')
        with self.locked():
            doc = self._load(request_id)
            if doc['plan']['fingerprint'] != fingerprint:
                raise Refused('maintenance_request_conflict')
            # Critical: repeats after ANY start, including stale "running" state,
            # only return its durable record. Never call the adapter a second time.
            if doc['state'] != 'prepared':
                return self.view(doc)
            if doc['version'] < 2 or self.admission is None:
                raise Refused('maintenance_admission_required')
            if doc['version']==3 and (self.lifecycle is None or self.lifecycle.host is not self.host):
                raise Refused('maintenance_service_adapter_required')
            self._claim(request_id)
            now, mono = self._now()
            if not (0 <= now - doc['created_at'] < PREVIEW_TTL and 0 <= mono - doc['created_monotonic'] < PREVIEW_TTL):
                doc.update(state='expired', updated_at=now)
                self._write(request_id + '.json', doc)
                return self.view(doc)
            # Durable start boundary BEFORE all host commands, even if revalidation fails.
            doc.update(state='running', updated_at=now, started_at=now, started_monotonic=mono)
            self._write(request_id + '.json', doc)
            steps = self._steps(doc['plan'], doc['request_id'])

            def record(phase, data):
                if phase not in ('freeze-intent', 'write-gate-frozen', 'database-drained'):
                    self.admission.verify_frozen(doc['events'][1]['data'])
                index = len(doc['events'])
                if index >= len(steps) or steps[index][0] != phase or not self._payload_equal(phase, data, steps[index][1]):
                    raise Refused('maintenance_journal_transition_invalid')
                at, _ = self._now()
                event = {'sequence': index + 1, 'phase': phase, 'data': copy.deepcopy(data), 'at': at,
                         'previous': doc['events'][-1]['digest'] if index else doc['binding']}
                event['digest'] = digest(event)
                next_doc = copy.deepcopy(doc)
                next_doc['events'].append(event)
                next_doc['updated_at'] = at
                if phase == 'drain-finished' and doc['version']<3:
                    next_doc['state'] = 'game_drained'
                elif phase == 'writers-stopped':
                    next_doc['state'] = 'writers_stopped'
                self._write(request_id + '.json', next_doc)
                doc.clear()
                doc.update(next_doc)

            try:
                record(*steps[0])
                token = self.admission.freeze(request_id, doc['plan']['identity'], doc['plan']['admission'])
                record('write-gate-frozen', token)
                proof = self.admission.drain(doc['plan']['admission'], token)
                record('database-drained', proof)
                GameDrain(self.host).execute(doc['plan'], record)
                if doc['version']==3:self.lifecycle.stop(doc['plan'],record)
            except Exception as error:
                # Read back after uncertain fsync/replace. A failed receipt write
                # must not overwrite a successful final receipt or lose an intent.
                prior = self._load(request_id)
                if prior['state'] not in ('game_drained','writers_stopped'):
                    prior.update(state='needs_review', error=error_code(error), updated_at=self._now()[0])
                    self._write(request_id + '.json', prior)
                return self.view(prior)
            return self.view(self._load(request_id))

    def observe(self, request_id):
        """Read-only reconciliation. Observation NEVER grants a permit or replays.

        Caller may inspect after process/response loss. A clean-looking exit does
        not retroactively prove an unrecorded signal was sent or game data saved.
        """
        doc = self._load(request_id)
        result = {'request_id': request_id, 'recorded_state': doc['state'],
                  'collected_at': self._now()[0], 'state': 'unknown', 'games': [],
                  'maintenance_permit': False, 'can_replay': False, 'can_resume': False}
        try:
            plan = doc['plan']
            if doc['version']==3:
                observed=ServiceLifecycle(self.host).observe(plan,doc['events'])
                result.update(state='observed',services=observed,games=[x for x in observed if x['service'] in plan['service_cycle']['games']])
                return result
            if self.host.identity() != plan['identity']:
                raise Refused('maintenance_drain_target_changed')
            states = self.host.services()
            if GameDrain.dependencies(states) != plan['dependencies']:
                raise Refused('maintenance_drain_dependencies_changed')
            active_games = {g['service'] for g in plan['games']}
            if (set(states) != set(plan['services_before'])
                    or any(list(row) != plan['services_before'][name] for name, row in states.items() if name not in active_games)):
                raise Refused('maintenance_unrelated_service_changed')
            observed = []
            for game in plan['games']:
                row, original = states[game['service']], game['before']
                item = {'service': game['service'], 'state': 'changed'}
                if row == (False, False, False, True, -1):
                    code, signum = self.host.exit_result(plan['identity']['container_id'], game['service'])
                    item['state'] = 'down_normal' if code == 0 and signum in (0, -1) else 'down_abnormal'
                elif row[0] and row[4] == original[4] and self.host.game_process(plan['identity'], row[4]) == game['process']:
                    if list(row) == original:
                        item['state'] = 'original'
                    elif not row[1] and not row[2]:
                        item['state'] = 'restart_inhibited'
                    elif not row[1] and row[2]:
                        item['state'] = 'restart_inhibited_marker_missing'
                observed.append(item)
            if self.host.identity() != plan['identity'] or self.host.services() != states:
                raise Refused('maintenance_observation_changed')
            result.update(state='observed', games=observed)
        except Exception as error:
            result['error'] = error_code(error)
        return result


class DrainMonitor:
    """Read-only, time-bounded exception for known game-drain transitions.

    This only keeps the GM process available to show progress. It never makes
    core_ok true, issues a write permit, resumes a service, or renews a timeout.
    Non-game dependencies, all other s6 services, versions, resources and the
    existing collector's auxiliary checks remain mandatory.
    """
    def __init__(self, coordinator, *, required_components=()):
        self.coordinator = coordinator
        self.required_components = tuple(required_components)

    def status(self):
        c = self.coordinator
        # Missing deployment is not an active transition. An existing corrupt
        # journal is unknown/failed, not a reason to bypass normal protection.
        if not os.path.lexists(c.root):
            return {'active': False, 'verified': False}
        try:
            c._directory()
            request_id = c._active()
            if request_id is None:
                return {'active': False, 'verified': False}
            doc = c._load(request_id)
            if doc['state'] in {'prepared', *TERMINAL_NO_EFFECT}:
                return {'active': False, 'verified': False}
            now, mono = c._now()
            # Allow fixed waits for each planned game plus probe/receipt overhead.
            # Neither a restart nor a read renews this absolute interval.
            duration = max(1, len(doc['plan']['games'])) * (TIMEOUT + 5) + 60
            if doc['version']==3:duration += len(doc['plan']['service_cycle']['stop_order'])*(STOP_TIMEOUT+10)
            result = {'active': True, 'verified': False, 'authority': 'drain-transition',
                      'request_id': request_id, 'phase': doc['state'],
                      'collected_at': now, 'expires_at': doc['started_at'] + duration,
                      'maintenance_permit': False}
            if not (0 <= now - doc['started_at'] < duration and 0 <= mono - doc['started_monotonic'] < duration):
                result['reason'] = 'maintenance_drain_observation_expired'
                return result
            games = {g['service'] for g in doc['plan']['games']}
            before = doc['plan']['services_before']
            # A component already broken before the request is not an expected
            # shutdown. Production passes the normal collector's full core list.
            if any(name not in before or (name not in games and
                   (before[name][:3] != [True, True, True] or before[name][4] < 1))
                   for name in self.required_components):
                result['reason'] = 'maintenance_preexisting_component_failure'
                return result
            # The collector has no application DB credentials. Re-read only the
            # root-owned gate token; an old journal alone cannot waive protection.
            gate = c.admission.gate if c.admission is not None else WriteGateManager(
                '/var/lib/dnf-gm/write-gate', owner=c.owner)
            tokens = [e['data'] for e in doc['events'] if e['phase'] == 'write-gate-frozen']
            if len(tokens) != 1:
                result['reason'] = 'maintenance_freeze_not_proven'
                return result
            gate.check_frozen(tokens[0])
            observation = c.observe(request_id)
            if observation['state'] != 'observed':
                result['reason'] = observation.get('error', 'maintenance_observation_unknown')
                return result
            known = {'original', 'restart_inhibited', 'restart_inhibited_marker_missing', 'down_normal','down_terminated'}
            if any(g['state'] not in known for g in observation.get('services',observation['games'])):
                result['reason'] = 'maintenance_drain_unexpected_state'
                return result
            # Do not race over a cancellation/state update; observation alone is
            # never allowed to update the durable execution history.
            if c._active() != request_id or c._load(request_id) != doc:
                result['reason'] = 'maintenance_journal_changed'
                return result
            after, after_mono = c._now()
            if not (0 <= after - doc['started_at'] < duration and 0 <= after_mono - doc['started_monotonic'] < duration):
                result['reason'] = 'maintenance_drain_observation_expired'
                return result
            gate.check_frozen(tokens[0])
            result.update(verified=True, games=observation['games'])
            if 'services' in observation:result['services']=observation['services']
            return result
        except Exception as error:
            return {'active': True, 'verified': False, 'authority': 'drain-transition',
                    'reason': error_code(error), 'maintenance_permit': False}
