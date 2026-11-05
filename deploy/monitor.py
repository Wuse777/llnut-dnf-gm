"""Root-owned local configuration; no credentials or commands from the web app."""
from pathlib import Path, PurePosixPath
import hashlib
import ipaddress
import json
import re
import os
import stat
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener, HTTPRedirectHandler

from monitor_runtime import command, run

CONFIG = Path('/etc/dnf-gm/monitor.json')


def validate(cfg):
    if type(cfg.get('inventory_maintenance_enabled', False)) is not bool:
        raise ValueError('Maintenance mode must be an explicit boolean')
    for name in [cfg['container'], *cfg['core_services'], *cfg['components']]:
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.@-]{0,127}', name):
            raise ValueError('Invalid local service identifier')
    u = urlsplit(cfg['gateway_url'])
    if u.scheme != 'http' or u.username or u.password or not ipaddress.ip_address(u.hostname).is_loopback:
        raise ValueError('Gateway health must use a numeric loopback HTTP address')
    for field in ('pvf_path', 'disk_path'):
        if not PurePosixPath(cfg[field]).is_absolute():
            raise ValueError('Absolute maintenance paths required')
    if not cfg['core_services'] or not cfg['components'] or len(set(cfg['components'])) != len(cfg['components']):
        raise ValueError('Explicit unique component and core service lists required')
    for field, floor in [('min_memory_mib', 256), ('min_swap_free_mib', 1536)]:
        if type(cfg[field]) is not int or cfg[field] < floor:
            raise ValueError('Protection threshold cannot be lowered below baseline')
    paths = cfg.get('storage_paths', [])
    if not isinstance(paths, list) or len(paths) > 8:
        raise ValueError('At most eight fixed storage roots')
    ids = set()
    for item in paths:
        if not isinstance(item, dict) or set(item) != {'id', 'label', 'path'}:
            raise ValueError('Explicit storage id/label/path required')
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,31}', item['id']) or item['id'] in ids:
            raise ValueError('Unique storage identifiers required')
        ids.add(item['id'])
        if not isinstance(item['label'], str) or not 1 <= len(item['label']) <= 48:
            raise ValueError('Short storage label required')
        path = PurePosixPath(item['path'])
        if not path.is_absolute() or '..' in path.parts or str(path) == '/':
            raise ValueError('Fixed non-root absolute storage path required')
    return cfg


class Collector:
    def __init__(self, cfg, auxiliary=None, maintenance=None, attestation=None):
        self.cfg, self.auxiliary = cfg, auxiliary
        self.attestation = attestation
        self.cached_sig = self.pvf_sha = None
        self.native_sig = self.native_sha = None
        self.maintenance = maintenance
        if self.maintenance is None and cfg.get('inventory_maintenance_enabled', False):
            from inventory_window import MonitorWindow
            self.maintenance = MonitorWindow(cfg)

    def native_fingerprint(self, pid):
        # Fixed image path, not a path accepted from the web. A missing/changed
        # optional protocol fingerprint never changes core health/protection.
        if type(pid) is not int or pid <= 1:
            self.native_sig = self.native_sha = None
            return None
        path = Path(f'/proc/{pid}/root/home/template/neople/monitor/df_monitor_r')
        return self._native_file_fingerprint(path)

    def _native_file_fingerprint(self, path):
        def signature(st):
            return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
        try:
            st = path.lstat()
            if not stat.S_ISREG(st.st_mode) or not 0 < st.st_size <= 15 * 1024 * 1024:
                raise ValueError('Unsupported program file')
            sig = (str(path), *signature(st))
            if sig != self.native_sig:
                digest = hashlib.sha256()
                remaining = st.st_size
                with path.open('rb') as stream:
                    if signature(os.fstat(stream.fileno())) != signature(st):
                        raise ValueError('Program replaced')
                    while remaining:
                        block = stream.read(min(remaining, 65536))
                        if not block:
                            raise ValueError('Short program read')
                        remaining -= len(block)
                        digest.update(block)
                    if stream.read(1) or signature(os.fstat(stream.fileno())) != signature(st):
                        raise ValueError('Program changed')
                if signature(path.lstat()) != signature(st):
                    raise ValueError('Program path changed')
                self.native_sig, self.native_sha = sig, digest.hexdigest()
            return self.native_sha
        except (OSError, ValueError):
            self.native_sig = self.native_sha = None
            return None

    def __call__(self):
        cfg = self.cfg
        services = {name: command(['systemctl', 'is-active', '--quiet', name], probe='service_state').returncode == 0
                    for name in cfg['core_services']}
        result = command(['docker', 'inspect', '-f', '{{json .State}}|{{.Image}}', cfg['container']], probe='container_state')
        if result.returncode:
            raise RuntimeError('Container unavailable')
        raw_state, image = result.stdout.strip().split('|', 1)
        state = json.loads(raw_state)
        # Validated names are positional arguments, never interpolated shell code.
        script = 'for name do printf "%s=" "$name"; s6-svstat "/run/service/$name" || exit 1; done'
        result = command(['docker', 'exec', cfg['container'], 'sh', '-c', script, 'gm-components', *cfg['components']],
                         probe='dnf_components')
        lines = result.stdout.splitlines()
        services['dnf_components'] = (result.returncode == 0 and len(lines) == len(cfg['components'])
                                      and all(line.startswith(name + '=up ') for name, line in zip(cfg['components'], lines))
                                      and bool(state.get('Running')) and not state.get('OOMKilled', True))
        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        try:
            with build_opener(ProxyHandler({}), NoRedirect()).open(cfg['gateway_url'], timeout=3) as response:
                services['dnf_gateway'] = response.status == 200
        except Exception:
            services['dnf_gateway'] = False
        if self.auxiliary:
            services['auxiliary_core'] = self.auxiliary()
        pvf = Path(cfg['pvf_path'])
        st = pvf.stat()
        sig = (st.st_ino, st.st_size, st.st_mtime_ns)
        if sig != self.cached_sig:
            with pvf.open('rb') as f:
                sha = hashlib.file_digest(f, 'sha256').hexdigest()
            after = pvf.stat()
            if sig != (after.st_ino, after.st_size, after.st_mtime_ns):
                raise RuntimeError('PVF changed while hashing')
            self.pvf_sha, self.cached_sig = sha, sig
        status = dict(services=services, core_ok=all(services.values()), pvf_sha256=self.pvf_sha, image_digest=image,
                      native_monitor_sha256=self.native_fingerprint(state.get('Pid')))
        if self.maintenance is not None:
            window = self.maintenance.status()
            if window.get('active') is True:
                # A permit never makes the game healthy. Ordinary writes keep
                # failing their core_ok guard throughout the maintenance window.
                status['core_ok'] = False
                status['state'] = 'maintenance'
                if (not all(services[name] for name in cfg['core_services'])
                        or services.get('auxiliary_core') is False):
                    window = {**window, 'verified': False, 'reason': 'non_game_core_failed'}
                elif (window.get('authority') == 'drain-transition' and services.get('dnf_gateway') is not True
                      and window.get('gateway_exit_expected') is not True):
                    # Game-only drain cannot waive gateway failure. Full writer
                    # drain may do so only after the root observer verifies the
                    # original gate token, target state and durable signal intent.
                    window = {**window, 'verified': False, 'reason': 'maintenance_gateway_failed'}
            status['maintenance'] = window
        if self.attestation is not None:
            status['maintenance_monitor'] = self.attestation()
        return status


def main():
    st = CONFIG.stat()
    if st.st_uid != 0 or st.st_mode & 0o022:
        raise ValueError('Monitor config must be root-owned and not group/world writable')
    cfg = validate(json.loads(CONFIG.read_text()))
    from telemetry import Recorder
    try:
        recorder = Recorder('/var/lib/dnf-gm/telemetry.sqlite', storage_paths=cfg.get('storage_paths', []))
    except Exception:
        recorder = None
        from monitor_runtime import event
        event('telemetry_unavailable')
    try:
        collector = Collector(cfg)
        if cfg.get('inventory_maintenance_enabled', False):
            from maintenance_readiness import InstalledMonitor, MonitorAttestation
            collector.attestation = MonitorAttestation(InstalledMonitor(), cfg)
        run(collector, disk_path=cfg['disk_path'], min_memory=cfg['min_memory_mib'], min_swap=cfg['min_swap_free_mib'], telemetry=recorder)
    finally:
        if recorder:
            recorder.close()


if __name__ == '__main__':
    main()
