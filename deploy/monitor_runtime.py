"""Bounded GM protection controller. No game writes or core-service mutations."""
from collections import deque
from pathlib import Path
import json
import os
import subprocess
import time

DEST = Path('/run/dnf-gm/status.json')
STATE = Path('/var/lib/dnf-gm/protection.json')
INHIBIT = Path('/var/lib/dnf-gm/no-auto-recover')
UNIT = 'dnf-gm.service'


def event(name, **fields):
    # Never log argv, command output, exception messages or credentials.
    print(json.dumps(dict(event=name, timestamp=time.time(), **fields)), flush=True)


def command(args, *, probe):
    started = time.monotonic()
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=8, check=False)
    except subprocess.TimeoutExpired:
        event('probe_timeout', probe=probe, timeout_seconds=8)
        raise
    finally:
        elapsed = time.monotonic() - started
        if elapsed >= 5:
            event('probe_slow', probe=probe, elapsed_seconds=round(elapsed, 3))


def atomic(path, data):
    tmp = path.with_suffix('.tmp')
    with tmp.open('w') as f:
        json.dump(data, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def resources(disk_path):
    values = {s.split(':')[0]: int(s.split()[1]) for s in Path('/proc/meminfo').read_text().splitlines()
              if s.startswith(('MemAvailable:', 'SwapFree:'))}
    fs = os.statvfs(disk_path)
    return dict(mem_available_mib=values['MemAvailable'] // 1024,
                swap_free_mib=values['SwapFree'] // 1024,
                disk_free_gib=round(fs.f_bavail * fs.f_frsize / 2**30, 2))


def cpu():
    nums = list(map(int, Path('/proc/stat').read_text().splitlines()[0].split()[1:9]))
    return sum(nums), nums[3] + nums[4]


class Protection:
    """Count fresh observations, never count the same cached failure twice."""
    def __init__(self):
        self.low = self.bad = self.errors = self.good = 0
        self.error_since = self.good_since = None

    def observe(self, now, resource_ok, *, sampled=False, core_ok=None):
        self.low = 0 if resource_ok else self.low + 1
        if not resource_ok:
            self.good = 0
            self.good_since = None
        if self.low >= 2:
            return 'resource_failure'
        if not sampled:
            return None
        if core_ok is None:
            self.errors += 1
            if self.error_since is None:
                self.error_since = now
            self.bad = self.good = 0
            self.good_since = None
            if self.errors >= 3 and now - self.error_since >= 60:
                return 'collector_failed'
        else:
            self.errors = 0
            self.error_since = None
            self.bad = 0 if core_ok else self.bad + 1
            if core_ok and resource_ok:
                if not self.good:
                    self.good_since = now
                self.good += 1
            else:
                self.good = 0
                self.good_since = None
            if self.bad >= 2:
                return 'core_failure'
        return None

    def recovered(self, now):
        return self.good >= 3 and now - self.good_since >= 30


def unit_state():
    result = command(['systemctl', 'show', UNIT, '--property=ActiveState,InactiveEnterTimestampMonotonic'],
                     probe='gm_state')
    if result.returncode:
        raise RuntimeError('GM state unavailable')
    values = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    return values['ActiveState'], values['InactiveEnterTimestampMonotonic']


class Controller:
    def __init__(self):
        # Recovery ownership deliberately does not survive monitor restarts.
        self.pending = None
        self.restarts = deque()

    def apply(self, reason, recovered, now):
        while self.restarts and now - self.restarts[0] >= 3600:
            self.restarts.popleft()
        if reason:
            if reason != 'collector_failed' and self.pending:
                self.pending = None
                atomic(STATE, dict(stopped_at=time.time(), reason=reason, manual_restart_required=True))
            active, _ = unit_state()
            if active != 'active':
                return
            result = command(['systemctl', 'stop', 'dnf-gm.service'], probe='stop_gm')
            if result.returncode:
                raise RuntimeError('GM stop failed')
            active, token = unit_state()
            automatic = reason == 'collector_failed' and active == 'inactive' and len(self.restarts) < 3 and not INHIBIT.exists()
            self.pending = token if automatic else None
            atomic(STATE, dict(stopped_at=time.time(), reason=reason, manual_restart_required=not automatic,
                               auto_recovery_pending=automatic))
            event('protection_stop', reason=reason, auto_recovery_pending=automatic)
        elif self.pending and recovered:
            token, self.pending = self.pending, None
            active, current_token = unit_state()
            if active != 'inactive' or token != current_token or INHIBIT.exists() or len(self.restarts) >= 3:
                event('auto_recovery_cancelled')
                atomic(STATE, dict(reason='auto_recovery_cancelled', manual_restart_required=True,
                                   auto_recovery_pending=False))
                return
            # Only our own collector-failure stop can reach this fixed command.
            self.restarts.append(now)
            result = command(['systemctl', 'start', 'dnf-gm.service'], probe='recover_gm')
            success = result.returncode == 0
            previous = json.loads(STATE.read_text())
            previous.update(auto_recovery_pending=False, manual_restart_required=not success,
                            recovered_at=time.time() if success else None,
                            recovery_result='started' if success else 'failed')
            atomic(STATE, previous)
            event('auto_recovery', success=success)


def run(collect, *, disk_path, min_memory=256, min_swap=1536):
    DEST.parent.mkdir(mode=0o755, exist_ok=True)
    STATE.parent.mkdir(mode=0o755, exist_ok=True)
    policy, controller = Protection(), Controller()
    baseline = cpu()
    next_collect = 0
    collection_failed = False
    while True:
        sampled, core_ok = False, None
        try:
            metrics = resources(disk_path)
            if time.monotonic() >= next_collect:
                sampled = True
                try:
                    status = collect()
                    metrics = resources(disk_path)
                    core_ok = status['core_ok'] is True
                    total, idle = cpu()
                    old_total, old_idle = baseline
                    baseline = total, idle
                    status.update(collected_at=time.time(), collector_pid=os.getpid(), **metrics,
                                  cpu_percent=round(100 * (1 - (idle - old_idle) / max(1, total - old_total)), 1))
                    atomic(DEST, status)
                    if collection_failed:
                        event('collection_recovered', core_ok=core_ok)
                    collection_failed = False
                except Exception as error:
                    core_ok = None
                    collection_failed = True
                    # Immediately fail closed: no stale fingerprints or healthy flag.
                    atomic(DEST, dict(collected_at=time.time(), core_ok=False, state='unknown',
                                      error_type=type(error).__name__, **metrics))
                    event('collection_failed', error_type=type(error).__name__)
                finally:
                    # Back off on failures too; avoid continuous Docker probes.
                    next_collect = time.monotonic() + 15
            safe = (metrics['mem_available_mib'] >= min_memory and metrics['swap_free_mib'] >= min_swap
                    and metrics['disk_free_gib'] >= 2)
            if not safe:
                atomic(DEST, dict(collected_at=time.time(), core_ok=False, state='resource_protection', **metrics))
            now = time.monotonic()
            reason = policy.observe(now, safe, sampled=sampled, core_ok=core_ok)
            controller.apply(reason, policy.recovered(now), now)
        except Exception as error:
            # A broken controller or resource reader must never authorize writes.
            atomic(DEST, dict(collected_at=time.time(), core_ok=False, state='unknown', error_type=type(error).__name__))
            event('monitor_failed', error_type=type(error).__name__)
            raise  # systemd retries the monitor; recovery ownership is discarded.
        time.sleep(5)
