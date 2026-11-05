"""Read-only rollback compatibility check, after GM has been quiesced.

Old selectors treated unknown target modes as a broad filter. Never hand an
accounts schedule (even a paused/cancelled one that can be copied) to that code.
No player names, request bodies or credentials are printed. No database writes.
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


class IncompatibleRollback(RuntimeError):
    pass


def check(q, target):
    manifest = Path(target) / 'deploy/release-features.json'
    supported = set()
    if manifest.exists():
        if manifest.stat().st_size > 4096:
            raise IncompatibleRollback('Invalid target release feature manifest')
        data = json.loads(manifest.read_text())
        modes = data.get('reward_target_modes')
        if data.get('schema_version') != 1 or not isinstance(modes, list) or any(not isinstance(m, str) for m in modes):
            raise IncompatibleRollback('Invalid target release feature manifest')
        supported = set(modes)
    if 'accounts' in supported:
        return
    q.execute("SELECT COUNT(*) n FROM information_schema.TABLES WHERE TABLE_SCHEMA='dnf_gm' AND TABLE_NAME='schedules'")
    if not q.fetchone()['n']:
        return
    # Native JSON validation fails closed on malformed stored requests. Includes
    # historical definitions because old UIs can copy/reactivate them.
    q.execute("SELECT 1 AS found FROM dnf_gm.schedules WHERE JSON_UNQUOTE(JSON_EXTRACT(request_json, '$.reward_job.targets.mode'))='accounts' LIMIT 1")
    if q.fetchone():
        raise IncompatibleRollback('Target cannot read account-list schedules. Use a compatible release; preserve tasks and audit history.')


def main():
    import os
    from dnfgm.config import Settings
    from dnfgm.db import Database
    if os.geteuid() != 0 or len(sys.argv) != 2:
        raise SystemExit('Root and one previous-release path required')
    target = Path(sys.argv[1]).resolve()
    if target.parent != Path('/opt/dnf-gm/releases'):
        raise SystemExit('Expected versioned release')
    try:
        settings = Settings(**json.loads(Path('/etc/dnf-gm/config.json').read_text())).check()
        with Database(settings).connect() as c, c.cursor() as q:
            check(q, target)
    except IncompatibleRollback as exc:
        raise SystemExit(str(exc))
    except Exception:
        raise SystemExit('Rollback compatibility could not be verified; no release switch permitted') from None
    print('Rollback target compatibility checked; no database changes')


if __name__ == '__main__':
    main()
