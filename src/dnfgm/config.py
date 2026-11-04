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
    cleanup_enabled: bool = False
    cleanup_manifest: str = '/run/dnf-gm/cleanup.json'
    cleanup_dir: str = '/var/lib/dnf-gm/cleanup'
    telemetry_file: str = '/var/lib/dnf-gm/telemetry.sqlite'
    catalog_file: str = '/var/lib/dnf-gm/catalog.sqlite'
    static_dir: str = ''
    assets_dir: str = ''
    image_digest: str = ''
    pvf_sha256: str = ''
    write_approvals: dict = field(default_factory=dict)
    mail_stack_limits: dict = field(default_factory=dict)
    native_monitor_enabled: bool = False
    native_control_actions: tuple = ()
    batch_worker_enabled: bool = False
    batch_worker_interval: int = 1
    schedule_worker_enabled: bool = False
    inventory_program_sha256: str = ''

    def check(self):
        if len(self.secret) < 32 or not self.db_password:
            raise ValueError('Private secret and dedicated database password required')
        if self.db_user.lower() in ('root', 'game'):
            raise ValueError('Application cannot run with maintenance/game credentials')
        if not self.origins or any(urlsplit(o).path or urlsplit(o).query or not urlsplit(o).hostname for o in self.origins):
            raise ValueError('Origins must be exact scheme://host[:port]')
        if self.public and any(not o.startswith('https://') for o in self.origins):
            raise ValueError('Public mode requires HTTPS origins')
        if not set(self.writes) <= {'currency', 'mail', 'ban', 'unban', 'equipment-unlock', 'reward', 'batch-reward', 'item-edit', 'item-reclaim', 'item-restore'}:
            raise ValueError('Unknown write capability')
        if self.writes and not self.image_digest:
            raise ValueError('Explicit server image fingerprint required for writes')
        if self.writes and (len(self.pvf_sha256) != 64 or any(c not in '0123456789abcdef' for c in self.pvf_sha256)):
            raise ValueError('Explicit PVF SHA-256 required for writes')
        if any(a.startswith('item-') for a in self.writes):
            import re
            if (not re.fullmatch(r'[a-f0-9]{64}', self.inventory_program_sha256)
                    or not re.fullmatch(r'sha256:[a-f0-9]{64}', self.image_digest)):
                raise ValueError('Inventory writes require exact game program and image fingerprints')
        if self.require_totp:
            raise ValueError('This distribution supports password-only bootstrap; TOTP enrollment is not implemented')
        for action in self.writes:
            if self.write_approvals.get(action) is not True:
                raise ValueError('Write capability has no explicit activation record')
        if type(self.native_monitor_enabled) is not bool:
            raise ValueError('Native monitor enable flag must be boolean')
        if self.native_monitor_enabled:
            from .native_monitor import private_ipv4
            if not private_ipv4(self.db_host) or not self.image_digest:
                raise ValueError('Native monitor requires an explicit private IPv4 database host and image fingerprint')
        if (not isinstance(self.native_control_actions, (tuple, list))
                or any(not isinstance(a, str) or a not in ('native-notice', 'native-kick')
                       for a in self.native_control_actions)
                or len(set(self.native_control_actions)) != len(self.native_control_actions)):
            raise ValueError('Unknown or duplicate native control action')
        if self.native_control_actions:
            if not self.native_monitor_enabled:
                raise ValueError('Native control requires fingerprinted native monitor activation')
            if any(self.write_approvals.get(a) is not True for a in self.native_control_actions):
                raise ValueError('Native control requires explicit action activation records')
        if type(self.schedule_worker_enabled) is not bool:
            raise ValueError('Schedule worker enabled must be a boolean')
        if type(self.batch_worker_enabled) is not bool:
            raise ValueError('Batch worker enabled must be a boolean')
        if type(self.batch_worker_interval) is not int or not 1 <= self.batch_worker_interval <= 60:
            raise ValueError('Batch worker interval must be 1..60 seconds')
        if self.batch_worker_enabled and 'batch-reward' not in self.writes:
            raise ValueError('Batch worker requires explicit batch-reward activation')
        if not isinstance(self.assets_dir,str) or (self.assets_dir and not Path(self.assets_dir).is_absolute()):
            raise ValueError('Assets directory must be empty or an absolute private path')
        if not isinstance(self.telemetry_file, str) or not Path(self.telemetry_file).is_absolute():
            raise ValueError('Telemetry file must be an absolute maintenance path')
        if type(self.cleanup_enabled) is not bool:
            raise ValueError('Cleanup enable flag must be boolean')
        for path in (self.cleanup_manifest, self.cleanup_dir):
            if not isinstance(path, str) or not Path(path).is_absolute():
                raise ValueError('Absolute maintenance cleanup paths required')
        # Deprecated compatibility key: old per-item caps no longer affect
        # startup, previews or issuance. No PVF-bound quantity overrides needed.
        return self


def load_settings():
    p = Path(os.environ.get('DNFGM_CONFIG', '/etc/dnf-gm/config.json'))
    if p.stat().st_mode & 0o077:
        raise ValueError('Configuration must be private (0600)')
    return Settings(**json.loads(p.read_text())).check()
