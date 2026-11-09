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


def check(q, target, *, gameplay_gate_configured=False):
    manifest = Path(target) / 'deploy/release-features.json'
    supported = set();data = {}
    if manifest.exists():
        if manifest.stat().st_size > 4096:
            raise IncompatibleRollback('Invalid target release feature manifest')
        data = json.loads(manifest.read_text())
        modes = data.get('reward_target_modes')
        if data.get('schema_version') != 1 or not isinstance(modes, list) or any(not isinstance(m, str) for m in modes):
            raise IncompatibleRollback('Invalid target release feature manifest')
        supported = set(modes)
    if gameplay_gate_configured and data.get('gameplay_transaction_fence') != 1:
        raise IncompatibleRollback('Target lacks the configured gameplay transaction fence. Preserve maintenance configuration and use a compatible release.')
    if 'accounts' not in supported:
        q.execute("SELECT COUNT(*) n FROM information_schema.TABLES WHERE TABLE_SCHEMA='dnf_gm' AND TABLE_NAME='schedules'")
        if q.fetchone()['n']:
            q.execute("SELECT 1 AS found FROM dnf_gm.schedules WHERE JSON_UNQUOTE(JSON_EXTRACT(request_json, '$.reward_job.targets.mode'))='accounts' LIMIT 1")
            if q.fetchone():
                raise IncompatibleRollback('Target cannot read account-list schedules. Use a compatible release; preserve tasks and audit history.')
    if not manifest.exists() or data.get('web_capability_policy') != 1:
        q.execute("SELECT COUNT(*) n FROM information_schema.TABLES WHERE TABLE_SCHEMA='dnf_gm' AND TABLE_NAME='capability_policy'")
        if q.fetchone()['n']:
            q.execute('SELECT revision FROM dnf_gm.capability_policy WHERE id=1')
            row=q.fetchone()
            if row and row['revision']>0:
                raise IncompatibleRollback('Target ignores web-managed permissions. Use a policy-aware release; do not delete permission history.')

    if data.get('maintenance_requests') != 1:
        q.execute("SELECT COUNT(*) n FROM information_schema.TABLES WHERE TABLE_SCHEMA='dnf_gm' AND TABLE_NAME='operations'")
        if q.fetchone()['n']:
            q.execute("SELECT 1 AS found FROM dnf_gm.operations WHERE action='maintenance' LIMIT 1")
            if q.fetchone():
                raise IncompatibleRollback('Target cannot reconcile web maintenance requests. Preserve requests and use a compatible release.')
        q.execute("SELECT COUNT(*) n FROM information_schema.TABLES WHERE TABLE_SCHEMA='dnf_gm' AND TABLE_NAME='capability_policy'")
        if q.fetchone()['n']:
            q.execute("SELECT 1 AS found FROM dnf_gm.capability_policy WHERE id=1 AND JSON_CONTAINS(enabled_json, '\"maintenance\"') LIMIT 1")
            if q.fetchone():
                raise IncompatibleRollback('Target cannot read the web maintenance capability. Use a compatible release; do not discard policy history.')

    if data.get('campaign_rewards') != 1:
        # Old workers ignore campaign binding and bypass the shared claim. A
        # finished/cancelled batch or schedule can still seed a copied task, so
        # its status must not exempt it from this compatibility check. Manual
        # reward previews also remain confirmable through their original ID.
        for table, paths in (
            ('reward_jobs', ('$.campaign_id', '$.reward.campaign_id')),
            ('schedules', ('$.reward_job.campaign_id', '$.reward_job.reward.campaign_id')),
            ('operations', ('$.campaign_id',)),
        ):
            q.execute("SELECT COUNT(*) n FROM information_schema.TABLES WHERE TABLE_SCHEMA='dnf_gm' AND TABLE_NAME=%s", (table,))
            if q.fetchone()['n']:
                condition = ' OR '.join("JSON_UNQUOTE(JSON_EXTRACT(request_json, %s)) NOT IN ('','null')" for _ in paths)
                q.execute('SELECT 1 AS found FROM dnf_gm.' + table + ' WHERE ' + condition + ' LIMIT 1', paths)
                if q.fetchone():
                    raise IncompatibleRollback('Target cannot preserve campaign reward claims. Use a campaign-aware release; preserve bound tasks, original operations and audit history.')

    if data.get('game_backup_requests') != 1:
        q.execute("SELECT COUNT(*) n FROM information_schema.TABLES WHERE TABLE_SCHEMA='dnf_gm' AND TABLE_NAME='game_backup_runs'")
        if q.fetchone()['n']:
            # needs_review and any future/unknown state still require an owner
            # to reconcile the original request. Only explicit terminal states
            # are safe to leave as history in an older release.
            q.execute("SELECT 1 AS found FROM dnf_gm.game_backup_runs WHERE state NOT IN ('succeeded','failed') LIMIT 1")
            if q.fetchone():
                raise IncompatibleRollback('Target cannot reconcile unfinished game backup requests. Finish or review the original request and use a compatible release.')


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
            check(q, target, gameplay_gate_configured=bool(settings.gameplay_gate_dir))
    except IncompatibleRollback as exc:
        raise SystemExit(str(exc))
    except Exception:
        raise SystemExit('Rollback compatibility could not be verified; no release switch permitted') from None
    print('Rollback target compatibility checked; no database changes')


if __name__ == '__main__':
    main()
