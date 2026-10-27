"""Root-owned local configuration; no credentials or commands from the web app."""
from pathlib import Path, PurePosixPath
import hashlib
import ipaddress
import json
import re
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener, HTTPRedirectHandler

from monitor_runtime import command, run

CONFIG = Path('/etc/dnf-gm/monitor.json')


def validate(cfg):
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
    return cfg


class Collector:
    def __init__(self, cfg, auxiliary=None):
        self.cfg, self.auxiliary = cfg, auxiliary
        self.cached_sig = self.pvf_sha = None

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
        return dict(services=services, core_ok=all(services.values()), pvf_sha256=self.pvf_sha, image_digest=image)


def main():
    st = CONFIG.stat()
    if st.st_uid != 0 or st.st_mode & 0o022:
        raise ValueError('Monitor config must be root-owned and not group/world writable')
    cfg = validate(json.loads(CONFIG.read_text()))
    run(Collector(cfg), disk_path=cfg['disk_path'], min_memory=cfg['min_memory_mib'], min_swap=cfg['min_swap_free_mib'])


if __name__ == '__main__':
    main()
