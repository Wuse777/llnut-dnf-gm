"""Privileged local collector; the only mutation is stopping dnf-gm.service.

Configuration is root-owned, never supplied by the web application. No shell,
credentials, log bodies, arbitrary HTTP targets, or core-service restart API.
"""
from pathlib import Path
import hashlib
import ipaddress
import json
import os
import re
import subprocess
import time
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener

DEST = Path('/run/dnf-gm/status.json')
STATE = Path('/var/lib/dnf-gm/protection.json')
CONFIG = Path('/etc/dnf-gm/monitor.json')


def command(args):
    return subprocess.run(args, capture_output=True, text=True, timeout=8, check=False)


def validate(d):
    for name in [d['container'], *d['core_services'], *d['components']]:
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.@-]{0,127}', name):
            raise ValueError('Invalid local service identifier')
    u = urlsplit(d['gateway_url'])
    if u.scheme != 'http' or u.username or u.password or not ipaddress.ip_address(u.hostname).is_loopback:
        raise ValueError('Gateway health must use a numeric loopback HTTP address')
    for field in ('pvf_path', 'disk_path'):
        if not Path(d[field]).is_absolute():
            raise ValueError('Absolute maintenance paths required')
    if not d['core_services'] or not d['components']:
        raise ValueError('Explicit core service and component lists required')
    for field, floor in [('min_memory_mib', 256), ('min_swap_free_mib', 1536)]:
        if type(d[field]) is not int or d[field] < floor:
            raise ValueError('Protection threshold cannot be lowered below baseline')
    return d


def atomic(p, data):
    tmp = p.with_suffix('.tmp')
    with tmp.open('w') as f:
        json.dump(data, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, 0o644)
    os.replace(tmp, p)


def memory():
    values = {s.split(':')[0]: int(s.split()[1]) for s in Path('/proc/meminfo').read_text().splitlines()
              if s.startswith(('MemAvailable:', 'SwapFree:'))}
    return values['MemAvailable'] // 1024, values['SwapFree'] // 1024


def cpu():
    nums = list(map(int, Path('/proc/stat').read_text().splitlines()[0].split()[1:9]))
    return sum(nums), nums[3] + nums[4]


def inspect_core(cfg):
    services = {name: command(['systemctl', 'is-active', '--quiet', name]).returncode == 0
                for name in cfg['core_services']}
    result = command(['docker', 'inspect', '-f', '{{json .State}}|{{.Image}}', cfg['container']])
    if result.returncode:
        raise RuntimeError('Container unavailable')
    raw_state, image = result.stdout.strip().split('|', 1)
    state = json.loads(raw_state)
    components = []
    for name in cfg['components']:
        r = command(['docker', 'exec', cfg['container'], 's6-svstat', '/run/service/' + name])
        components.append(r.returncode == 0 and r.stdout.startswith('up '))
    services['dnf_components'] = all(components) and bool(state.get('Running')) and not state.get('OOMKilled', True)
    try:
        with build_opener(ProxyHandler({})).open(cfg['gateway_url'], timeout=3) as response:
            services['dnf_gateway'] = response.status == 200
    except Exception:
        services['dnf_gateway'] = False
    return services, image


def main():
    DEST.parent.mkdir(mode=0o755, exist_ok=True)
    STATE.parent.mkdir(mode=0o755, exist_ok=True)
    cfg = None
    baseline = cpu()
    cached_sig = pvf_sha = None
    failures = 0
    last_collect = 0
    core_ok = False
    while True:
        try:
            if cfg is None:
                st = CONFIG.stat()
                if st.st_uid != 0 or st.st_mode & 0o022:
                    raise ValueError('Monitor config must be root-owned and not group/world writable')
                cfg = validate(json.loads(CONFIG.read_text()))
            mem, swap = memory()
            if time.monotonic() - last_collect >= 15:
                services, image = inspect_core(cfg)
                pvf = Path(cfg['pvf_path'])
                st = pvf.stat()
                sig = (st.st_ino, st.st_size, st.st_mtime_ns)
                if sig != cached_sig:
                    with pvf.open('rb') as f:
                        pvf_sha = hashlib.file_digest(f, 'sha256').hexdigest()
                    cached_sig = sig
                total, idle = cpu()
                old_total, old_idle = baseline
                baseline = total, idle
                usage = round(100 * (1 - (idle - old_idle) / max(1, total - old_total)), 1)
                fs = os.statvfs(cfg['disk_path'])
                core_ok = all(services.values())
                atomic(DEST, dict(collected_at=time.time(), cpu_percent=usage, mem_available_mib=mem,
                                 swap_free_mib=swap, disk_free_gib=round(fs.f_bavail * fs.f_frsize / 2**30, 2),
                                 services=services, core_ok=core_ok, pvf_sha256=pvf_sha, image_digest=image))
                last_collect = time.monotonic()
            unsafe = mem < cfg['min_memory_mib'] or swap < cfg['min_swap_free_mib'] or not core_ok
            failures = failures + 1 if unsafe else 0
            reason = 'resource_or_core_failure'
        except Exception as error:
            atomic(DEST, dict(collected_at=time.time(), core_ok=False, state='unknown', error_type=type(error).__name__))
            failures += 1
            reason = 'collector_failed'
        if failures >= 2:
            atomic(STATE, dict(stopped_at=time.time(), reason=reason, manual_restart_required=True))
            command(['systemctl', 'stop', 'dnf-gm.service'])
            failures = 0
        time.sleep(5)


if __name__ == '__main__':
    main()
