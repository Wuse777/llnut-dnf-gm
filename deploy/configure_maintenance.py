#!/usr/bin/env python3
"""Installer-only maintenance wiring. Preserves owner switches; no game commands.

An independently reviewed inventory-maintenance.json is required for execution.
Missing policy leaves a usable ordinary GM installation, not fabricated support.
"""
import os
from pathlib import Path
import pwd
import stat
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from dnfgm.config import Settings
from dnfgm.inventory_fence import directory
from dnfgm.release_files import Refused, read_json
from configure_task_probe import read_private, replace_private
from inventory_probe import validate as validate_policy
from maintenance_readiness import compatible
from monitor import validate as validate_monitor


def make_directory(path,mode,owner,group):
    directory(path.parent,owner)
    try:path.mkdir(mode=mode)
    except FileExistsError:pass
    st=path.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid!=owner:raise Refused('maintenance_directory_untrusted')
    os.chown(path,owner,group);os.chmod(path,mode)


def configure(*, app=Path('/etc/dnf-gm/config.json'), monitor=Path('/etc/dnf-gm/monitor.json'),
              policy=Path('/etc/dnf-gm/inventory-maintenance.json'),
              root=Path('/var/lib/dnf-gm/maintenance-requests'), state=Path('/var/lib/dnf-gm/maintenance-drain'),
              owner=0,app_gid):
    for path in (app,monitor,policy):directory(path.parent,owner)
    original=read_private(app,(owner,),0o027);value=original[0];settings=Settings(**value).check()
    if Path(settings.maintenance_dir)!=root:raise Refused('maintenance_outbox_path_changed')
    # App can write the inbox only. Plans, receipts and results stay root-owned.
    make_directory(root,0o755,owner,owner)
    make_directory(root/'results',0o755,owner,owner)
    make_directory(root/'bindings',0o700,owner,owner)
    make_directory(root/'inbox',0o770,owner,app_gid)
    make_directory(state,0o700,owner,owner)
    if not policy.exists():
        return {'configured':False,'reason':'reviewed_policy_missing','game_commands':False}
    config=validate_policy(read_json(policy,owner=owner,limit=65536))
    if (settings.image_digest!=config['image_digest'] or settings.pvf_sha256!=config['pvf_sha256']
            or settings.inventory_program_sha256!=config['program_sha256']):
        raise Refused('maintenance_application_version_changed')
    old_monitor=read_private(monitor,(owner,),0o022)
    updated_monitor={**old_monitor[0],'inventory_maintenance_enabled':True,
                     'core_services':list(config['protected_services'].values())}
    validate_monitor(updated_monitor);compatible(updated_monitor,config)
    updated={**value,'db_connection_limit':2}
    Settings(**updated).check()
    if updated!=value:replace_private(app,updated,original,(owner,),0o027)
    if updated_monitor!=old_monitor[0]:replace_private(monitor,updated_monitor,old_monitor,(owner,),0o022)
    return {'configured':True,'game_commands':False,'connection_budget':3}


def main():
    if os.geteuid()!=0 or len(sys.argv)!=1:raise SystemExit('Root-only fixed installation configuration')
    try:result=configure(app_gid=pwd.getpwnam('dnfgm').pw_gid)
    except Exception:raise SystemExit('Maintenance wiring refused; preserve the original policy/configuration. No game command was sent.') from None
    print('Maintenance directories and monitor configured.' if result['configured'] else
          'Maintenance transport prepared; reviewed process policy is not installed. Ordinary GM remains available.')


if __name__=='__main__':main()
