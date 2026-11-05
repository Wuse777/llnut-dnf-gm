"""Read-only installer guard; caller holds the shared deployment/maintenance lock.

Never starts/stops a service or edits a journal. A running drain leaves logical
ownership behind even after its process releases flock; switching code at that
point would lose the adapter needed to reconcile and restore the original plan.
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from dnfgm.inventory_fence import _read, directory
from dnfgm.release_files import Refused, read_json
from maintenance_drain import DrainCoordinator, STATE, TERMINAL_NO_EFFECT

RUNTIME = Path('/run/dnf-gm/maintenance')
GATE = Path('/var/lib/dnf-gm/write-gate')
CONFIG = Path('/etc/dnf-gm/config.json')


def assert_idle(*, state=STATE, runtime=RUNTIME, gate=GATE, owner=0):
    state, runtime = Path(state), Path(runtime)
    if os.path.lexists(gate):
        from maintenance_gate import WriteGateManager
        manager=WriteGateManager(gate,owner=owner)
        with manager.locked(False):
            if manager.read()['state']!='open':raise Refused('maintenance_game_writes_frozen')
    if os.path.lexists(runtime):
        directory(runtime, owner)
        if os.path.lexists(runtime / 'permit.json'):
            # Even an expired/invalid permit must be deliberately closed first.
            raise Refused('maintenance_window_not_closed')
        if os.path.lexists(runtime / 'closed.json'):
            receipt = _read(runtime, 'closed.json', owner, 4096)
            if not isinstance(receipt, dict) or receipt.get('safe_to_resume') is not True:
                raise Refused('maintenance_window_not_reconciled')
    if not os.path.lexists(state):
        return
    c = DrainCoordinator(state, None, owner=owner, lock_path=state / 'coordinator.lock')
    c._directory()
    request_id = c._active()
    if request_id is None:
        # A brand-new empty journal is harmless. A missing pointer next to a
        # durable request is an uncertain installation/recovery state, not idle.
        with os.scandir(state) as entries:
            for entry in entries:
                if entry.name != 'coordinator.lock':
                    raise Refused('maintenance_journal_unresolved')
        return
    if c._load(request_id)['state'] not in TERMINAL_NO_EFFECT:
        raise Refused('maintenance_request_not_finished')


def assert_config_gate(config=CONFIG, *, owner=0):
    """Also inspect a previously configured path; never silently switch it."""
    config=Path(config)
    directory(config.parent,owner)
    # Legacy files may be app-owned but the parent must be root-controlled.
    cfg=read_json(config,limit=65536)
    if not isinstance(cfg,dict):raise Refused('maintenance_config_invalid')
    path=cfg.get('gameplay_gate_dir','')
    if not isinstance(path,str):raise Refused('maintenance_config_invalid')
    if path:
        gate=Path(path)
        if not gate.is_absolute() or '..' in gate.parts:raise Refused('maintenance_config_invalid')
        from maintenance_gate import WriteGateManager
        manager=WriteGateManager(gate,owner=owner)
        # Missing CONFIGURED state is unknown, not a new unconfigured install.
        with manager.locked(False):
            if manager.read()['state']!='open':raise Refused('maintenance_game_writes_frozen')


def main():
    try:
        assert_idle()
        assert_config_gate()
    except Exception:
        # No paths, subprocess output, player data or tracebacks in deployment logs.
        print('GM维护记录尚未结束或无法核验。请在原版本中核对并结束维护后再发布；本检查未停止服务。', file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
