from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from urllib.parse import urlsplit


@dataclass
class Settings:
    db_host: str = '127.0.0.1'
    db_port: int = 4000
    db_user: str = 'dnf_gm_app'
    db_password: str = ''
    secret: str = ''
    origins: tuple = ('http://127.0.0.1:8765',)
    public: bool = False
    require_totp: bool = False
    writes: tuple = ()
    test_uids: tuple = (-1,)
    status_file: str = '/run/dnf-gm/status.json'
    catalog_file: str = '/var/lib/dnf-gm/catalog.sqlite'
    static_dir: str = ''
    image_digest: str = ''
    pvf_sha256: str = ''
    write_approvals: dict = field(default_factory=dict)

    def check(self):
        if len(self.secret) < 32 or not self.db_password:
            raise ValueError('Private secret and dedicated database password required')
        if self.db_user.lower() in ('root', 'game'):
            raise ValueError('Application cannot run with maintenance/game credentials')
        if not self.origins or any(urlsplit(o).path or urlsplit(o).query or not urlsplit(o).hostname for o in self.origins):
            raise ValueError('Origins must be exact scheme://host[:port]')
        if self.public and any(not o.startswith('https://') for o in self.origins):
            raise ValueError('Public mode requires HTTPS origins')
        if not set(self.writes) <= {'currency', 'mail', 'ban', 'unban'}:
            raise ValueError('Unknown write capability')
        if self.writes and not self.image_digest:
            raise ValueError('Explicit server image fingerprint required for writes')
        if self.writes and (len(self.pvf_sha256) != 64 or any(c not in '0123456789abcdef' for c in self.pvf_sha256)):
            raise ValueError('Explicit PVF SHA-256 required for writes')
        if self.require_totp:
            raise ValueError('This distribution supports password-only bootstrap; TOTP enrollment is not implemented')
        for action in self.writes:
            if self.write_approvals.get(action) is not True:
                raise ValueError('Write capability has no explicit activation record')
        return self


def load_settings():
    p = Path(os.environ.get('DNFGM_CONFIG', '/etc/dnf-gm/config.json'))
    if p.stat().st_mode & 0o077:
        raise ValueError('Configuration must be private (0600)')
    return Settings(**json.loads(p.read_text())).check()
