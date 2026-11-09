#!/usr/bin/env python3
"""Install fixed game-backup source wiring; no locks, game writes or service commands.

Default installation discovers the full business-schema inventory through the
already-reviewed private management-backup source. Copy and rehearsal remain
unconfigured until an operator supplies a root-only complete settings file.
"""
import argparse
import os
from pathlib import Path
import stat
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import pymysql
from dnfgm.config import Settings
from dnfgm.game_backup import inventory, sql, SYSTEM_SCHEMAS, write_new
from dnfgm.inventory_fence import directory
from configure_task_probe import read_private
from backup_worker import configuration as management_configuration
from game_backup_worker import CONFIG, ROOT, configuration


def discover(connection):
    c = pymysql.connect(**connection, charset='utf8mb4', autocommit=True,
                        connect_timeout=3, read_timeout=10, write_timeout=10, local_infile=False)
    try:
        schemas = sorted(set(r[0] for r in sql(c, 'SHOW DATABASES')) - SYSTEM_SCHEMAS)
        catalog = inventory(c, schemas)
        tables = {(t['schema'], t['name']) for t in catalog['tables']}
        relations = []
        for name, child, cc, parent, pc in [
            ('characters_account', ('taiwan_cain', 'charac_info'), 'm_id', ('d_taiwan', 'accounts'), 'UID'),
            ('inventory_character', ('taiwan_cain_2nd', 'inventory'), 'charac_no', ('taiwan_cain', 'charac_info'), 'charac_no'),
            ('statistics_character', ('taiwan_cain', 'charac_stat'), 'charac_no', ('taiwan_cain', 'charac_info'), 'charac_no')]:
            if child in tables and parent in tables:
                relations.append({'name': name, 'child_schema': child[0], 'child_table': child[1], 'child_column': cc,
                                  'parent_schema': parent[0], 'parent_table': parent[1], 'parent_column': pc})
        return {'version': 1, 'connection': connection, 'schemas': schemas, 'relations': relations, 'copy': None, 'lab': None}
    finally:
        c.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings-file', help='Root-owned 0600 complete reviewed settings JSON')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise ValueError('Root-only installation')
    app = Path('/etc/dnf-gm/config.json')
    directory(app.parent, 0)
    settings = Settings(**read_private(app, (0,), 0o027)[0]).check()
    ROOT.parent.mkdir(mode=0o700, exist_ok=True)
    directory(ROOT.parent, 0)
    ROOT.mkdir(mode=0o700, exist_ok=True)
    directory(ROOT, 0)
    if ROOT.stat().st_mode & 0o077:
        raise ValueError('Game restore-point root must be private')
    if args.settings_file:
        source = Path(args.settings_file)
        directory(source.parent, 0)
        value = read_private(source, (0,), 0o077)[0]
        # Validate before publication, including fixed source match and explicit
        # remote/lab targets. No plaintext configuration goes to stdout.
        configuration(source, settings)
        if CONFIG.exists():
            raise ValueError('Existing settings preserved; review and replace privately before rerunning')
        write_new(CONFIG, value)
    elif not CONFIG.exists():
        backup_config = Path('/etc/dnf-gm/backup.json')
        if not backup_config.exists():
            print('Game restore points remain unconfigured; private source is not installed.')
            return
        original = management_configuration(backup_config, settings)
        connection = {k: original[k] for k in ('host', 'port', 'user', 'password')}
        try:
            value = discover(connection)
        except Exception:
            # An unsupported game schema must disable this optional feature,
            # rather than make an otherwise valid GM upgrade fail. Explicit
            # supplied or already installed settings still fail closed below.
            print('Game restore points remain unconfigured; source discovery needs private operator review.')
            return
        write_new(CONFIG, value)
    configuration(CONFIG, settings)
    print('Fixed game source installed; offsite copy and rehearsal require explicit destinations. No game/service commands sent.')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('Game backup setup refused; credentials and SQL details suppressed.') from None
