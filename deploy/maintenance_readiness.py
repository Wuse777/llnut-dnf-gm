"""Fixed installed-monitor handshake. Read-only, no service control or permit.

A healthy-looking old JSON file is insufficient: bind the loaded release/config,
boot/PID/start time and two clocks to the currently active systemd main process.
"""
import hashlib
import importlib
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time

from dnfgm.release_files import Refused, canonical, read_json
from dnfgm.inventory_fence import directory

ROOT = Path('/opt/dnf-gm/current')
MONITOR_CONFIG = Path('/etc/dnf-gm/monitor.json')
POLICY = Path('/etc/dnf-gm/inventory-maintenance.json')
STATUS = Path('/run/dnf-gm/status.json')
PROTOCOL = 1
TTL = 40
DEPLOY_MODULES = ('monitor', 'monitor_runtime', 'inventory_window', 'inventory_probe',
    'game_drain', 'service_lifecycle', 'maintenance_drain', 'maintenance_gate',
    'maintenance_admission', 'maintenance_session_state', 'maintenance_session_monitor',
    'maintenance_readiness')
APP_MODULES = ('inventory_fence', 'release_files', 'write_gate_state',
    'gameplay_transactions', 'ordinary_reconcile')
SOURCES = {**{name: 'deploy/' + name + '.py' for name in DEPLOY_MODULES},
           **{'dnfgm.' + name: 'src/dnfgm/' + name + '.py' for name in APP_MODULES}}


def digest(value): return hashlib.sha256(canonical(value)).hexdigest()


def compatible(monitor, policy):
    normalize = lambda name: name.removesuffix('.service')
    if (monitor.get('inventory_maintenance_enabled') is not True
            or monitor['container'] != policy['container'] or monitor['pvf_path'] != policy['pvf_path']
            or not set(monitor['components']) <= set(policy['components'])
            or {normalize(n) for n in monitor['core_services']} !=
               {normalize(n) for n in policy['protected_services'].values()}):
        raise Refused('maintenance_monitor_config_mismatch')


def source_hash(root, owner):
    root = Path(root).resolve(strict=True)
    directory(root, owner)
    hashes = {}
    for relative in SOURCES.values():
        path = root / relative
        # Fixed paths only. A writable intermediate directory is not trusted.
        parent = path.parent
        while parent != root:
            directory(parent, owner); parent = parent.parent
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            before = os.fstat(fd)
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != owner or before.st_mode & 0o022
                    or before.st_nlink != 1 or not 0 < before.st_size <= 1024 * 1024):
                raise Refused('maintenance_monitor_source_untrusted')
            raw = os.read(fd, 1024 * 1024 + 1)
            after = os.fstat(fd)
            fingerprint = lambda st: (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
            if (len(raw) != before.st_size or fingerprint(before) != fingerprint(after)
                    or fingerprint(path.lstat()) != fingerprint(before)):
                raise Refused('maintenance_monitor_source_changed')
            hashes[relative] = hashlib.sha256(raw).hexdigest()
        finally: os.close(fd)
    return digest(hashes)


def verify_loaded(root):
    """Reject sys.path selecting another release even if disk current is correct."""
    for name, relative in SOURCES.items():
        module = sys.modules.get('__main__') if name == 'monitor' else None
        if module is None or Path(getattr(module, '__file__', '')).resolve() != root / relative:
            module = importlib.import_module(name)
        if Path(getattr(module, '__file__', '')).resolve() != root / relative:
            raise Refused('maintenance_monitor_loaded_release_mismatch')


def process_identity(proc, pid):
    if type(pid) is not int or pid <= 1: raise Refused('maintenance_monitor_process_invalid')
    proc = Path(proc)
    raw = (proc / str(pid) / 'stat').read_text()
    tail = raw[raw.rfind(')')+2:].split()
    if len(tail) < 20 or tail[0] in ('Z','X','x'):
        raise Refused('maintenance_monitor_process_invalid')
    ticks = int(tail[19])
    boot = (proc / 'sys/kernel/random/boot_id').read_text().strip()
    if ticks <= 0 or not re.fullmatch('[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}', boot):
        raise Refused('maintenance_monitor_process_invalid')
    return {'collector_pid': pid, 'process_start_ticks': ticks, 'boot_id': boot}


def main_pid():
    result = subprocess.run(['systemctl','show','dnf-gm-monitor.service','--property=ActiveState,MainPID'],
        capture_output=True, text=True, timeout=3, check=False)
    if result.returncode or len(result.stdout) > 1024:
        raise Refused('maintenance_monitor_service_unavailable')
    fields = dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
    if fields.get('ActiveState') != 'active' or not fields.get('MainPID','').isdigit():
        raise Refused('maintenance_monitor_service_unavailable')
    return int(fields['MainPID'])


class InstalledMonitor:
    def __init__(self, *, root=ROOT, config=MONITOR_CONFIG, policy=POLICY, owner=0):
        self.root, self.config, self.policy, self.owner = Path(root), Path(config), Path(policy), owner

    def configuration(self):
        directory(self.config.parent, self.owner); directory(self.policy.parent, self.owner)
        monitor = read_json(self.config, owner=self.owner, limit=65536)
        policy = read_json(self.policy, owner=self.owner, limit=65536)
        from monitor import validate as validate_monitor
        from inventory_probe import validate as validate_policy
        validate_monitor(monitor); validate_policy(policy); compatible(monitor, policy)
        return monitor, policy

    def snapshot(self):
        root = self.root.resolve(strict=True)
        monitor, policy = self.configuration()
        data = {'version': PROTOCOL, 'release_sha256': digest(str(root)),
                'source_sha256': source_hash(root, self.owner),
                'monitor_config_sha256': digest(monitor), 'policy_sha256': digest(policy)}
        if self.root.resolve(strict=True) != root: raise Refused('maintenance_monitor_release_changed')
        return data, monitor, policy


class MonitorAttestation:
    """Created by the actual collector, then latched for this process lifetime."""
    def __init__(self, installed, monitor_cfg, *, pid=None, proc=Path('/proc'), monotonic=time.monotonic):
        self.installed, self.proc, self.monotonic = installed, Path(proc), monotonic
        self.pid = os.getpid() if pid is None else pid
        self.original, cfg, _ = installed.snapshot()
        if cfg != monitor_cfg: raise Refused('maintenance_monitor_loaded_config_mismatch')
        verify_loaded(installed.root.resolve(strict=True))
        self.process = process_identity(self.proc, self.pid)

    def __call__(self):
        current, _, _ = self.installed.snapshot()
        if current != self.original or process_identity(self.proc, self.pid) != self.process:
            raise Refused('maintenance_monitor_loaded_state_changed')
        return {**self.original, **self.process, 'collected_monotonic': self.monotonic()}


class MonitorHandshake:
    def __init__(self, installed, *, status=STATUS, proc=Path('/proc'), pid_provider=main_pid,
                 clock=time.time, monotonic=time.monotonic):
        self.installed, self.status, self.proc = installed, Path(status), Path(proc)
        self.pid_provider, self.clock, self.monotonic = pid_provider, clock, monotonic

    def check(self, expected_policy, *, healthy=True):
        if healthy is not None and type(healthy) is not bool:
            raise Refused('maintenance_monitor_check_mode_invalid')
        expected, cfg, policy = self.installed.snapshot()
        if policy != expected_policy: raise Refused('maintenance_monitor_policy_changed')
        pid = self.pid_provider()
        process = process_identity(self.proc, pid)
        cmdline = (self.proc / str(pid) / 'cmdline').read_bytes()
        parts = cmdline.rstrip(b'\0').split(b'\0')
        if (len(parts) != 2 or len(cmdline) > 4096
                or Path(os.fsdecode(parts[1])).resolve() != self.installed.root.resolve() / 'deploy/monitor.py'):
            raise Refused('maintenance_monitor_command_mismatch')
        sample = read_json(self.status, owner=self.installed.owner, limit=65536)
        attested = sample.get('maintenance_monitor')
        fields = set(expected) | set(process) | {'collected_monotonic'}
        if (not isinstance(attested, dict) or set(attested) != fields
                or any(type(attested.get(k)) is not type(v) or attested[k] != v for k,v in (expected|process).items())
                or sample.get('collector_pid') != pid):
            raise Refused('maintenance_monitor_attestation_mismatch')
        now, mono = self.clock(), self.monotonic()
        at, sampled_mono = sample.get('collected_at'), attested['collected_monotonic']
        if (any(type(t) not in (int,float) or not math.isfinite(t) for t in (now,mono,at,sampled_mono))
                or not 0 <= now-at <= TTL or not 0 <= mono-sampled_mono <= TTL):
            raise Refused('maintenance_monitor_attestation_stale')
        if (sample.get('image_digest') != policy['image_digest'] or sample.get('pvf_sha256') != policy['pvf_sha256']
                or any(type(sample.get(k)) not in (int,float) or not math.isfinite(sample[k]) or sample[k] < minimum
                       for k,minimum in (('mem_available_mib',cfg['min_memory_mib']),('swap_free_mib',cfg['min_swap_free_mib']),('disk_free_gib',2)))):
            raise Refused('maintenance_monitor_snapshot_unhealthy')
        services = sample.get('services', {})
        if any(services.get(name) is not True for name in cfg['core_services']):
            raise Refused('maintenance_monitor_snapshot_unhealthy')
        if healthy:
            if (sample.get('core_ok') is not True or sample.get('maintenance',{}).get('active') is True
                    or services.get('dnf_components') is not True or services.get('dnf_gateway') is not True):
                raise Refused('maintenance_monitor_snapshot_unhealthy')
        elif healthy is False:
            from monitor_runtime import protection_health
            if protection_health(sample, now) is not True:
                raise Refused('maintenance_monitor_transition_unverified')
        if (self.pid_provider() != pid or process_identity(self.proc, pid) != process
                or self.installed.snapshot()[0] != expected):
            raise Refused('maintenance_monitor_changed_during_handshake')
        # This proof authorizes neither gameplay writes nor a maintenance window.
        return {**expected, **process, 'collected_at': at, 'collected_monotonic': sampled_mono,
                'checked_at': self.clock(), 'healthy': healthy, 'maintenance_permit': False}
