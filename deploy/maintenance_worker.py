#!/usr/bin/env python3
"""Fixed root daemon for authenticated web maintenance requests. No arbitrary commands."""
import argparse
from dataclasses import replace
import os
from pathlib import Path
import pwd
import signal
import sys
import threading
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from dnfgm.config import Settings
from dnfgm.db import Database
from dnfgm.inventory_fence import directory
from dnfgm.ordinary_reconcile import check_schema
from dnfgm.release_files import Refused
from configure_task_probe import read_private
from inventory_probe import LinuxProbe
from inventory_window import WindowManager, ROOT as WINDOW
from maintenance_admission import MaintenanceAdmission
from maintenance_drain import DrainCoordinator, STATE, GLOBAL_LOCK, error_code
from maintenance_executor import ExecutionWorker
from maintenance_gate import WriteGateManager
from maintenance_readiness import InstalledMonitor, MonitorHandshake
from maintenance_session import MaintenanceSession, RestoredHealth
from service_lifecycle import ServiceHost, ServiceLifecycle
from backup_worker import BackupWorker

APP=Path('/etc/dnf-gm/config.json')
OUTBOX=Path('/var/lib/dnf-gm/maintenance-requests')
GATE=Path('/var/lib/dnf-gm/write-gate')


def build(*, initialize=False):
    account=pwd.getpwnam('dnfgm')
    directory(APP.parent,0)
    value,st,_=read_private(APP,(0,),0o027)
    if st.st_nlink!=1:raise Refused('maintenance_config_untrusted')
    settings=Settings(**value).check()
    if (Path(settings.maintenance_dir)!=OUTBOX or Path(settings.gameplay_gate_dir)!=GATE
            or settings.db_connection_limit>2):
        raise Refused('maintenance_installation_required')
    installed=InstalledMonitor();_,policy=installed.configuration()
    if any(getattr(settings,k)!=policy[k] for k in ('image_digest','pvf_sha256')) or settings.inventory_program_sha256!=policy['program_sha256']:
        raise Refused('maintenance_application_version_changed')
    # The web process gets two connections and this single worker gets one.
    db=Database(replace(settings,db_connection_limit=1))
    probe=LinuxProbe(policy);host=ServiceHost(probe)
    coordinator=DrainCoordinator(STATE,host,lock_path=GLOBAL_LOCK,
        admission=MaintenanceAdmission(WriteGateManager(GATE),db),lifecycle=ServiceLifecycle(host))
    window=WindowManager(WINDOW,probe)
    if initialize:
        coordinator.initialize();window.initialize()
    session=MaintenanceSession(coordinator,window,RestoredHealth(host))
    worker=ExecutionWorker(OUTBOX,coordinator,account.pw_uid,session,MonitorHandshake(installed))
    worker.backups=BackupWorker(db,settings)
    return worker


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true',help='Read-only configuration, schema and monitor readiness check')
    args=parser.parse_args()
    if os.geteuid()!=0:raise SystemExit('Root required for the fixed maintenance worker')
    stop=threading.Event()
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:stop.set())
    try:
        worker=build(initialize=not args.check)
        if args.check:
            with worker.coordinator.admission.db.connect() as c,c.cursor() as q:check_schema(q)
            worker.handshake.check(worker.coordinator.host.cfg,healthy=None)
            print('Maintenance configuration, schema and installed monitor verified; no game commands sent.')
            return
    except Exception as error:
        print('Maintenance initialization refused: '+error_code(error),file=sys.stderr)
        raise SystemExit(1) from None
    last_error=None;last_log=0
    while not stop.is_set():
        try:
            worker.tick();last_error=None
            # Same thread and the same reserved connection slot, never concurrent.
            try:worker.backups.tick()
            except Exception:
                try:
                    with worker.backups.db.connect() as c,c.cursor() as q:backup_policy=worker.backups.control.policy(q)
                    worker.backups.report(backup_policy,'error','backup_worker_failed',True)
                except Exception:pass
                print('Management backup observation failed; no game command sent.',flush=True)
        except Exception as error:
            code=error_code(error);now=time.monotonic()
            if code!=last_error or now-last_log>=60:
                print('Maintenance worker observation: '+code,flush=True);last_error,last_log=code,now
        stop.wait(5)


if __name__=='__main__':main()
