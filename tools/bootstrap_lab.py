"""Download pinned official runtime files into a local directory; never uses sudo."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import urllib.request
p=argparse.ArgumentParser();p.add_argument('--runtime',required=True);a=p.parse_args()
r=Path(a.runtime).resolve();r.mkdir(parents=True,exist_ok=True)
root=Path(__file__).resolve().parents[1]
for entry in json.loads((root/'tools/runtime-sources.json').read_text()):
 path=r/entry['path'];path.parent.mkdir(parents=True,exist_ok=True)
 if not path.exists():
  tmp=path.with_suffix(path.suffix+'.part')
  with urllib.request.urlopen(entry['url'],timeout=60) as src,tmp.open('wb') as dst:
   import shutil;shutil.copyfileobj(src,dst,1024*1024)
  tmp.replace(path)
 if hashlib.file_digest(path.open('rb'),'sha256').hexdigest()!=entry['sha256']:
  raise SystemExit('Runtime checksum mismatch: '+entry['path'])
mysql=r/'mysql';mysql.mkdir(exist_ok=True)
wanted={'bin/mysql','bin/mysqld','bin/mysqldump','share/english/errmsg.sys'}
with tarfile.open(r/'downloads/mysql-5.7.44.tar.gz') as archive:
 for member in archive:
  name=member.name.split('/',1)[-1]
  if name not in wanted:continue
  member.name=name
  archive.extract(member,mysql,filter='data')
for name in ['libaio','libncurses5','libtinfo5']:
 subprocess.run(['dpkg-deb','-x',str(r/'downloads'/f'{name}.deb'),str(mysql/'deps')],check=True)
venv=r/'venv'
subprocess.run([sys.executable,'-m','venv','--without-pip',str(venv)],check=True)
env=os.environ.copy();env.pop('PYTHONPATH',None)
subprocess.run([str(venv/'bin/python'),str(r/'pip.pyz'),'install','--disable-pip-version-check','-r',str(root/'requirements.lock')],env=env,check=True)
print(json.dumps({'status':'ready','runtime':str(r),'global_packages_changed':False}))
