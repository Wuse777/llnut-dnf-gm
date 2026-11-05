"""Upgrade an existing GM management schema; never changes game rows or services.

Caller must stop GM and retain a private management backup first. DDL commits
independently: on a failure preserve the backup and inspect, never drop tables.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from dnfgm.release_files import maintenance_lock
from check_maintenance_idle import assert_idle, assert_config_gate
from provision import mysql
import grants

MIGRATIONS=tuple(sorted((Path(__file__).resolve().parents[1]/'migrations').glob('*.sql')))
GRANTS=('character_read_sql','catalog_policy_sql','mail_gold_sql','equipment_unlock_sql',
        'rewards_sql','mail_center_sql','warehouse_read_sql','item_preferences_sql',
        'reward_jobs_sql','native_controls_sql','schedules_sql','inventory_management_sql',
        'inventory_storage_sql','character_maintenance_sql','character_rename_sql','character_rescue_sql','character_quests_sql','quest_repair_sql','player_preferences_sql','backup_schedule_sql','support_sql','economy_sql','capability_policy_sql','gameplay_fence_sql')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--container',required=True)
    p.add_argument('--mysql-port',type=int,default=4000)
    p.add_argument('--db-account-host',required=True)
    p.add_argument('--backup',required=True,help='Existing private nonempty management dump')
    a=p.parse_args()
    if os.geteuid()!=0:raise SystemExit('Root required')
    backup=Path(a.backup);st=backup.lstat()
    import stat
    if not stat.S_ISREG(st.st_mode) or st.st_uid!=0 or st.st_mode&0o077 or st.st_size==0:
        raise SystemExit('Private management backup required')
    cfg=json.loads(Path('/etc/dnf-gm/config.json').read_text());name=cfg['db_user']
    if (not re.fullmatch(r'[A-Za-z0-9_]{1,32}',name) or name.lower() in ('root','game') or
            not re.fullmatch(r'[A-Za-z0-9_.:-]{1,255}',a.db_account_host) or
            not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}',a.container) or not 1<=a.mysql_port<=65535):
        raise SystemExit('Invalid maintenance target')
    with maintenance_lock(Path('/var/lib/dnf-gm/maintenance.lock')):
        for unit in ('dnf-gm.service','dnf-gm-maintenance.service'):
            result=subprocess.run(['systemctl','show',unit,'-p','ActiveState','--value'],capture_output=True,text=True,check=True)
            if result.stdout.strip() not in ('inactive','failed'):raise SystemExit('Stop GM workers before schema upgrade')
        assert_idle();assert_config_gate()
        versions={int(x) for x in mysql(a.container,a.mysql_port,'SELECT version FROM dnf_gm.schema_versions;').split()}
        if not {1,2,3}<=versions or not versions<=set(range(1,17)):raise SystemExit('Unsupported source schema')
        for path in MIGRATIONS:
            version=int(path.name.split('-')[0].split('.')[0])
            if version not in versions:
                mysql(a.container,a.mysql_port,path.read_text())
                print('Installed management migration',version,flush=True)
        user=f"'{name}'@'{a.db_account_host}'"
        mysql(a.container,a.mysql_port,'\n'.join(getattr(grants,f)(user) for f in GRANTS))
        mysql(a.container,a.mysql_port,grants.initialize_owner_capabilities_sql())
    print('Management migrations and dedicated grants installed; initial owner switches enabled. No game rows or services changed.')


if __name__=='__main__':main()
