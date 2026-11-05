"""Prepare the fixed gate during installation; never starts/stops game services.

Caller holds the deployment/maintenance lock and has stopped the GM worker.
Reinstallation preserves state and never reopens a freeze or replaces a lock.
"""
import json
import os
from pathlib import Path
import pwd
import stat
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from dnfgm.config import Settings
from dnfgm.db import Database
from dnfgm.gameplay_transactions import inspect_protocol
from dnfgm.inventory_fence import directory
from dnfgm.release_files import Refused
from configure_task_probe import read_private
from maintenance_gate import WriteGateManager

APP=Path('/etc/dnf-gm/config.json')
GATE=Path('/var/lib/dnf-gm/write-gate')


def configure(*, config=APP, root=GATE, owner=0, app_uid, app_gid, db_factory=Database):
    config,root=Path(config),Path(root)
    directory(config.parent,owner)
    original=read_private(config,(owner,app_uid),0o027)
    value,st,digest=original
    if st.st_nlink!=1:raise Refused('maintenance_config_untrusted')
    settings=Settings(**value).check()
    if settings.gameplay_gate_dir and Path(settings.gameplay_gate_dir)!=root:
        raise Refused('maintenance_config_gate_path_changed')
    # Existing schema number alone is insufficient. Fail before config changes
    # if the actual table/protocol or dedicated SELECT grant is missing.
    with db_factory(settings).connect() as c,c.cursor() as q:
        inspect_protocol(q)
    gate=WriteGateManager(root,owner=owner)
    state=gate.initialize()
    if state['state']!='open':raise Refused('maintenance_game_writes_frozen')
    updated={**value,'gameplay_gate_dir':str(root)}
    Settings(**updated).check()
    changed=updated!=value or (st.st_uid,st.st_gid,stat.S_IMODE(st.st_mode))!=(owner,app_gid,0o640)
    if changed:
        current=read_private(config,(owner,app_uid),0o027)
        if (current[1].st_dev,current[1].st_ino,current[2])!=(st.st_dev,st.st_ino,digest):
            raise Refused('maintenance_config_changed')
        body=(json.dumps(updated,ensure_ascii=False,indent=2)+'\n').encode()
        fd,name=tempfile.mkstemp(prefix='.write-gate-config-',dir=config.parent)
        try:
            with os.fdopen(fd,'wb') as stream:
                os.fchown(stream.fileno(),owner,app_gid)
                os.fchmod(stream.fileno(),0o640)
                stream.write(body);stream.flush();os.fsync(stream.fileno())
            os.replace(name,config)
            d=os.open(config.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            try:os.fsync(d)
            finally:os.close(d)
        finally:
            if os.path.exists(name):os.unlink(name)
    return {'configured':True,'changed':changed,'protocol_version':1,'services_changed':False}


def main():
    if os.geteuid()!=0 or len(sys.argv)!=1:raise SystemExit('Root-only fixed installation configuration')
    app=pwd.getpwnam('dnfgm')
    try:configure(app_uid=app.pw_uid,app_gid=app.pw_gid)
    except Exception:raise SystemExit('Write admission configuration could not be verified; preserve state and inspect the original installation. No game service was changed.') from None
    print('Persistent write admission configured; owner capabilities preserved. No game service changed.')


if __name__=='__main__':main()
