"""Manage only our marked, unprivileged socket-only MySQL laboratory."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from dnfgm_m0.lab import connect

p=argparse.ArgumentParser();p.add_argument('command',choices=['init','start','stop','status'])
p.add_argument('--runtime',required=True);a=p.parse_args();r=Path(a.runtime).resolve()
r.mkdir(parents=True,exist_ok=True)
marker=r/'m0-laboratory.json';data=r/'lab-data'
env=os.environ.copy();env['LD_LIBRARY_PATH']=':'.join(str(r/'mysql/deps'/s) for s in ['usr/lib/x86_64-linux-gnu','lib/x86_64-linux-gnu'])
if a.command=='init':
 if data.exists():raise SystemExit('Refuse to initialize an existing datadir')
 data.mkdir(mode=0o700)
 subprocess.run([str(r/'mysql/bin/mysqld'),'--no-defaults','--initialize-insecure','--basedir='+str(r/'mysql'),'--datadir='+str(data),'--log-error='+str(r/'lab-init.log')],env=env,check=True)
 marker.write_text(json.dumps({'purpose':'dnf-gm-m0-local-only','server_id':57044}))
else:
 if not marker.exists() or json.loads(marker.read_text()).get('purpose')!='dnf-gm-m0-local-only':
  raise SystemExit('Missing laboratory ownership marker')
 if a.command=='start':
  if (r/'mysql.sock').exists():raise SystemExit('Socket already exists; inspect status first')
  subprocess.Popen([str(r/'mysql/bin/mysqld'),'--no-defaults','--basedir='+str(r/'mysql'),'--datadir='+str(data),'--socket='+str(r/'mysql.sock'),'--pid-file='+str(r/'mysql.pid'),'--skip-networking','--server-id=57044','--innodb-buffer-pool-size=128M','--log-error='+str(r/'mysql.log')],env=env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
  for _ in range(100):
   try:c=connect(str(r/'mysql.sock'));c.close();break
   except Exception:time.sleep(.1)
  else:raise SystemExit('Startup failed; inspect private local log')
 elif a.command=='stop':
  c=connect(str(r/'mysql.sock'))
  try:
   with c.cursor() as cur:cur.execute('SHUTDOWN')
  finally:c.close()
 elif a.command=='status':
  c=connect(str(r/'mysql.sock'));c.close()
 print(json.dumps({'command':a.command,'status':'ok','tcp_enabled':False}))
