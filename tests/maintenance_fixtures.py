"""Synthetic database identity/proof; real filesystem gate. No game commands."""
import copy
import os
from types import SimpleNamespace

from maintenance_admission import MaintenanceAdmission, validate_plan
from maintenance_gate import WriteGateManager
from dnfgm.release_files import Refused


class SyntheticAdmission(MaintenanceAdmission):
    server_uuid = '12345678-1234-1234-1234-123456789abc'

    def prepare(self):
        self._configuration()
        with self.gate.locked(False):
            state = self.gate.read()
            if state['state'] != 'open':
                raise Refused('maintenance_game_writes_frozen')
            return copy.deepcopy(validate_plan({'version': 1, 'server_uuid': self.server_uuid, 'gate': state}))

    def drain(self, plan, token):
        self.verify_frozen(token)
        if plan['server_uuid'] != self.server_uuid:
            raise Refused('maintenance_database_identity_changed')
        return {'protocol_version': 1, 'ordinary_transactions_drained': True,
                **{k: token[k] for k in ('operation_id', 'generation', 'binding_sha256')},
                'server_uuid': self.server_uuid, 'checked_at': self.gate.clock(),
                'game_writes': False, 'maintenance_permit': False}


def admission(tmp_path, *, clock=None):
    options = {'owner': os.geteuid()}
    if clock is not None:
        options['clock'] = clock
    gate = WriteGateManager(tmp_path / 'write-admission', **options)
    gate.initialize()
    return SyntheticAdmission(gate, SimpleNamespace(settings=SimpleNamespace(gameplay_gate_dir=str(gate.root))))
