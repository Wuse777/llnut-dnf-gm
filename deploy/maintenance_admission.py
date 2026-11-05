"""Fixed database/admission precondition for the durable root drain coordinator.

No game writes, commands, replay or gate release. The original reviewed database
identity and open generation are part of the plan, not sampled after freezing.
"""
import copy
from pathlib import Path
import re

from dnfgm.gameplay_transactions import inspect_protocol
from dnfgm.release_files import Refused
from dnfgm.write_gate_state import validate
from maintenance_gate import binding_hash

UUID = re.compile(r'[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}')


def validate_plan(plan):
    if (not isinstance(plan, dict) or set(plan) != {'version', 'server_uuid', 'gate'}
            or type(plan['version']) is not int or plan['version'] != 1
            or not isinstance(plan['server_uuid'], str) or not UUID.fullmatch(plan['server_uuid'])):
        raise Refused('maintenance_admission_plan_invalid')
    state = validate(plan['gate'])
    if state['state'] != 'open' or state['generation'] >= 2147483647:
        raise Refused('maintenance_admission_plan_invalid')
    return plan


def validate_token(token, plan, request_id, identity):
    validate_plan(plan)
    validate(token)
    if (token['state'] != 'frozen' or token['generation'] != plan['gate']['generation'] + 1
            or token['operation_id'] != request_id or token['binding_sha256'] != binding_hash(identity)):
        raise Refused('maintenance_admission_token_mismatch')
    return token


def validate_proof(proof, plan, token):
    expected = {'protocol_version': 1, 'ordinary_transactions_drained': True,
                'operation_id': token['operation_id'], 'generation': token['generation'],
                'binding_sha256': token['binding_sha256'], 'server_uuid': plan['server_uuid'],
                'game_writes': False, 'maintenance_permit': False}
    import math
    if isinstance(proof,dict) and 'outcomes' in proof:
        from dnfgm.ordinary_reconcile import validate_summary
        validate_summary(proof['outcomes'])
        if proof['outcomes']['audit_id'] != 'maintenance-outcomes:' + token['operation_id']:
            raise Refused('maintenance_outcome_proof_invalid')
        expected['outcomes'] = proof['outcomes']
    if (not isinstance(proof, dict) or set(proof) != set(expected) | {'checked_at'}
            or any(type(proof[k]) is not type(v) or proof[k] != v for k, v in expected.items())
            or type(proof['checked_at']) not in (int, float)
            or not math.isfinite(proof['checked_at']) or proof['checked_at'] < 0):
        raise Refused('maintenance_admission_proof_invalid')
    return proof


class MaintenanceAdmission:
    def __init__(self, gate, db):
        self.gate, self.db = gate, db

    def _configuration(self):
        if not self.db.settings.gameplay_gate_dir or Path(self.db.settings.gameplay_gate_dir) != self.gate.root:
            raise Refused('maintenance_admission_configuration_mismatch')

    def prepare(self):
        self._configuration()
        with self.gate.locked(False):
            state = self.gate.read()
            if state['state'] != 'open':
                raise Refused('maintenance_game_writes_frozen')
            with self.db.connect() as c, c.cursor() as q:
                inspect_protocol(q)
                q.execute('SELECT @@server_uuid AS server_uuid')
                server = q.fetchone()['server_uuid']
            if self.gate.read() != state:
                raise Refused('maintenance_admission_changed')
            return copy.deepcopy(validate_plan({'version': 1, 'server_uuid': server, 'gate': state}))

    def verify_plan(self, plan):
        validate_plan(plan)
        if self.prepare() != plan:
            raise Refused('maintenance_admission_changed')

    def freeze(self, request_id, identity, plan):
        # Verify original DB identity before leaving the system frozen. Recheck
        # on the exclusive DB lock afterwards to cover replacement during freeze.
        self.verify_plan(plan)
        token = self.gate.freeze(request_id, identity, expected_state=plan['gate'])
        return validate_token(token, plan, request_id, identity)

    def drain(self, plan, token):
        self._configuration()
        validate_plan(plan)
        proof = self.gate.drain_database(token, self.db, expected_server_uuid=plan['server_uuid'], reconcile=True)
        return validate_proof(proof, plan, token)

    def verify_frozen(self, token):
        self._configuration()
        return self.gate.check_frozen(token)
