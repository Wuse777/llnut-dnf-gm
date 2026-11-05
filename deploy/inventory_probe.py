"""Fixed read-only Linux/Docker probes for an operator-arranged maintenance window.

Not a service controller. No SQL, signals, restart/stop, or arbitrary command API.
Process policies must be reviewed offline; there is deliberately no auto-learn.
"""
from pathlib import Path, PurePosixPath
import hashlib
import json
import os
import re
import selectors
import stat
import subprocess
import time

from dnfgm.inventory_fence import Refused
from dnfgm.release_files import canonical

NAME = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9_.@-]{0,127}\Z')
HEX = re.compile(r'[a-f0-9]{64}\Z')
# The complete directory inventory is returned, not just configured names. A new
# or omitted supervisor therefore invalidates the window. The full /proc check
# separately rejects finish scripts and writers; readiness alone is not proof.
S6_SCRIPT = '''set -eu
for dir in /run/service/*; do
  test -d "$dir" || continue
  printf '%s=' "${dir##*/}"
  s6-svstat -o up,wantedup,normallyup,ready,pid "$dir"
done'''


def path_ok(value):
    return isinstance(value, str) and value.startswith('/') and '..' not in PurePosixPath(value).parts and value != '/'


def validate(cfg):
    fields = {'container','components','protected_services','pvf_path','program_path',
              'image_digest','pvf_sha256','program_sha256','process_rules'}
    if not isinstance(cfg,dict) or set(cfg)-{'resident_components','dormant_components'} != fields:
        raise Refused('maintenance_config_invalid')
    if not isinstance(cfg['container'],str) or not NAME.fullmatch(cfg['container']):
        raise Refused('maintenance_config_invalid')
    components=cfg['components']
    if (not isinstance(components,list) or not 2<=len(components)<=64
            or any(not isinstance(n,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}',n) for n in components)
            or len(set(components))!=len(components) or 'mysql' not in components):
        raise Refused('maintenance_config_invalid')
    residents=cfg.get('resident_components',['mysql'])
    allowed_infrastructure={'mysql','s6-linux-init-shutdownd','s6rc-fdholder','s6rc-oneshot-runner'}
    if (not isinstance(residents,list) or not residents
            or any(not isinstance(n,str) or n not in components for n in residents)
            or len(residents)!=len(set(residents))
            or 'mysql' not in residents
            or any(n not in allowed_infrastructure and not n.endswith('-log') for n in residents)):
        raise Refused('maintenance_resident_policy_invalid')
    dormant=cfg.get('dormant_components',[])
    # These optional/template services are explicitly absent from the running
    # game, not a way to label a game writer as safe while its finish runs.
    if (not isinstance(dormant,list)
            or any(not isinstance(n,str) or n not in components or n not in
                   {'game_template','netbird','tailscale','tailscaled'} for n in dormant)
            or len(dormant)!=len(set(dormant)) or set(dormant)&set(residents)):
        raise Refused('maintenance_dormant_policy_invalid')
    services=cfg['protected_services']
    if (not isinstance(services,dict) or set(services)!={'docker','dnf','mihomo','cliproxyapi'}
            or any(not isinstance(n,str) or not NAME.fullmatch(n) or n.startswith('dnf-gm') for n in services.values())
            or len(set(services.values()))!=4):
        raise Refused('maintenance_config_invalid')
    if any(not path_ok(cfg[k]) for k in ('pvf_path','program_path')):
        raise Refused('maintenance_config_invalid')
    if (any(not isinstance(cfg[k],str) or not HEX.fullmatch(cfg[k]) for k in ('pvf_sha256','program_sha256'))
            or not isinstance(cfg['image_digest'],str) or not re.fullmatch(r'sha256:[a-f0-9]{64}',cfg['image_digest'])):
        raise Refused('maintenance_config_invalid')
    rules=cfg['process_rules']
    if not isinstance(rules,list) or not 2<=len(rules)<=256:
        raise Refused('maintenance_process_policy_missing')
    ids=set()
    for rule in rules:
        if (not isinstance(rule,dict) or set(rule)!={'id','role','exe','sha256','argv','uid','parents'}
                or not isinstance(rule['id'],str) or not NAME.fullmatch(rule['id']) or rule['id'] in ids
                or rule['role'] not in ('init','supervisor','logger','mysql') or not path_ok(rule['exe'])
                or not isinstance(rule['sha256'],str) or not HEX.fullmatch(rule['sha256'])
                or type(rule['uid']) is not int or not 0<=rule['uid']<=4294967294):
            raise Refused('maintenance_process_policy_invalid')
        ids.add(rule['id'])
        argv=rule['argv']; parents=rule['parents']
        if (not isinstance(argv,list) or not 1<=len(argv)<=64
                or any(not isinstance(v,str) or '\x00' in v or len(v.encode())>4096 for v in argv)
                or not isinstance(parents,list) or len(parents)>64
                or any(not isinstance(v,str) or not NAME.fullmatch(v) for v in parents)):
            raise Refused('maintenance_process_policy_invalid')
        if rule['role']=='init' and parents or rule['role']!='init' and not parents:
            raise Refused('maintenance_process_policy_invalid')
    if (sum(r['role']=='init' for r in rules)!=1 or sum(r['role']=='mysql' for r in rules)!=1
            or any(p not in ids for r in rules for p in r['parents'])):
        raise Refused('maintenance_process_policy_invalid')
    return cfg


def run_command(args, timeout):
    """Bounded stdout and wall time. Only this helper's fixed probe is killed."""
    with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as child:
        chunks=[]; size=0; end=time.monotonic()+timeout
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(child.stdout,selectors.EVENT_READ)
                while True:
                    left=end-time.monotonic()
                    if left<=0 or not selector.select(left):
                        raise Refused('maintenance_probe_timeout')
                    block=os.read(child.stdout.fileno(),8192)
                    if not block:break
                    size+=len(block)
                    if size>65536:raise Refused('maintenance_probe_output_large')
                    chunks.append(block)
            child.wait(timeout=max(0.001,end-time.monotonic()))
            if child.returncode:raise Refused('maintenance_probe_command_failed')
            return b''.join(chunks).decode('utf-8',errors='strict')
        finally:
            if child.poll() is None:
                child.kill(); child.wait()


def read_components(text, expected):
    """Parse the COMPLETE s6 inventory without asserting that it is quiescent."""
    rows={}
    if not isinstance(text,str) or len(text.encode())>65536:
        raise Refused('maintenance_components_invalid')
    for line in text.splitlines():
        name,separator,status=line.partition('=');parts=status.split()
        if (not separator or name in rows or len(parts)!=5
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}',name)
                or any(v not in ('true','false') for v in parts[:4])):
            raise Refused('maintenance_components_invalid')
        if not re.fullmatch(r'-1|[1-9][0-9]{0,9}',parts[4]):raise Refused('maintenance_components_invalid')
        rows[name]=(*[v=='true' for v in parts[:4]],int(parts[4]))
    if set(rows)!=set(expected):raise Refused('maintenance_components_changed')
    return rows


def parse_components(text, expected, residents=('mysql',), dormant=()):
    rows=read_components(text,expected)
    for name,row in rows.items():
        if name in residents:
            # mysql and several s6 infrastructure daemons do not notify ready.
            if not row[0] or not row[1] or not row[2] or row[4]<1:
                raise Refused('maintenance_mysql_down' if name=='mysql' else 'maintenance_infrastructure_down')
        elif name in dormant:
            if row[:3]!=(False,False,False) or row[4]!=-1:
                raise Refused('maintenance_dormant_service_active')
        elif row!=(False,False,False,True,-1):
            raise Refused('maintenance_writers_not_quiescent')
        # Only reviewed, initially-disabled optional/template services may have
        # ready=false. All writers require completed finish; the full process
        # policy additionally rejects ANY unapproved finish/writer process.
    return rows


def stat_identity(text):
    # comm can contain spaces or ')' so split after its LAST closing parenthesis.
    _,marker,tail=text.rpartition(') ')
    fields=tail.split()
    if not marker or len(fields)<20 or fields[0] in ('Z','X','x'):
        raise Refused('maintenance_process_unstable')
    return int(fields[1]),int(fields[19])  # ppid (field4), starttime (field22)


def cgroups(text):
    result={}
    for row in text.splitlines():
        parts=row.split(':',2)
        if len(parts)!=3 or parts[1] in result or not parts[2].startswith('/'):
            raise Refused('maintenance_cgroup_invalid')
        result[parts[1]]=parts[2].rstrip('/') or '/'
    if not result:raise Refused('maintenance_cgroup_invalid')
    return result


def in_container(actual, base):
    # A match on ANY non-root controller is conservatively included. Movement
    # into nested PID namespaces/cgroups is not allowed to hide game writers.
    return any(path!='/' and key in actual and (actual[key]==path or actual[key].startswith(path+'/')) for key,path in base.items())


class LinuxProbe:
    def __init__(self,cfg, *, runner=run_command, proc=Path('/proc'), clock=time.time, monotonic=time.monotonic):
        self.cfg=validate(cfg);self.runner=runner;self.proc=Path(proc);self.clock=clock;self.monotonic=monotonic
        self.cache={};self.deadline=0
        self.policy_sha256=hashlib.sha256(canonical(cfg)).hexdigest()

    def budget(self):
        left=self.deadline-self.monotonic()
        if left<=0:raise Refused('maintenance_probe_timeout')
        return min(5,left)

    def command(self,args):
        return self.runner(args,self.budget())

    def hash_file(self,path,limit, *, proc_exe=False):
        self.budget();path=Path(path)
        # proc/PID/exe is a kernel-managed symlink. Configuration paths may not
        # themselves be symlinks; ancestor trust belongs to the host operator.
        before=path.stat() if proc_exe else path.lstat()
        if not stat.S_ISREG(before.st_mode) or not 0<before.st_size<=limit:
            raise Refused('maintenance_program_invalid')
        sig=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
        key=sig(before) # shared binaries are hashed once across supervisor PIDs
        if key in self.cache:return self.cache[key]
        h=hashlib.sha256()
        flags=os.O_RDONLY if proc_exe else os.O_RDONLY|os.O_NOFOLLOW
        fd=os.open(path,flags)
        try:
            if sig(os.fstat(fd))!=sig(before):raise Refused('maintenance_file_changed')
            remaining=before.st_size
            while remaining:
                self.budget();block=os.read(fd,min(65536,remaining))
                if not block:raise Refused('maintenance_file_changed')
                h.update(block);remaining-=len(block)
            if os.read(fd,1) or sig(os.fstat(fd))!=sig(before) or sig(path.stat())!=sig(before):
                raise Refused('maintenance_file_changed')
        finally:os.close(fd)
        if len(self.cache)>256:self.cache.clear()
        self.cache[key]=h.hexdigest();return self.cache[key]

    def inspect(self):
        raw=self.command(['docker','inspect','-f','{{.Id}}|{{.Image}}|{{json .State}}',self.cfg['container']])
        cid,image,state_json=raw.strip().split('|',2)
        data={'Id':cid,'Image':image};state=json.loads(state_json)
        if (data.get('Image')!=self.cfg['image_digest'] or not isinstance(data.get('Id'),str) or not HEX.fullmatch(data['Id'])
                or state.get('Running') is not True or state.get('OOMKilled') is not False
                or state.get('Paused') is not False or state.get('Restarting') is not False
                or type(state.get('Pid')) is not int or state['Pid']<=1
                or not isinstance(state.get('StartedAt'),str) or not state['StartedAt']):
            raise Refused('maintenance_container_changed')
        return {'container_id':data['Id'],'container_started_at':state['StartedAt'],'image_digest':data['Image'],'pid':state['Pid']}

    def components(self):
        text=self.command(['docker','exec',self.cfg['container'],'sh','-c',S6_SCRIPT])
        return parse_components(text,self.cfg['components'],self.cfg.get('resident_components',['mysql']),self.cfg.get('dormant_components',[]))

    def process_rows(self,pid):
        base=cgroups((self.proc/str(pid)/'cgroup').read_text())
        if all(value=='/' for value in base.values()):raise Refused('maintenance_container_not_isolated')
        ns=(self.proc/str(pid)/'ns/pid').stat().st_ino
        rows=[];entries=list(self.proc.iterdir())
        if len(entries)>16384:raise Refused('maintenance_process_budget')
        for entry in entries:
            self.budget()
            if not entry.name.isdigit():continue
            try:
                cg=cgroups((entry/'cgroup').read_text())
            except FileNotFoundError:continue # an exited host process
            if not in_container(cg,base):continue
            if len(rows)>=256:raise Refused('maintenance_process_budget')
            if (entry/'ns/pid').stat().st_ino!=ns:raise Refused('maintenance_nested_namespace')
            start=(entry/'stat').read_text();ppid,ticks=stat_identity(start)
            exe=os.readlink(entry/'exe')
            if exe.endswith(' (deleted)'):raise Refused('maintenance_process_unstable')
            digest=self.hash_file(entry/'exe',128*1024*1024,proc_exe=True)
            raw=(entry/'cmdline').read_bytes()
            if not raw.endswith(b'\0') or len(raw)>16384:raise Refused('maintenance_process_unstable')
            argv=[v.decode('utf-8',errors='strict') for v in raw[:-1].split(b'\0')]
            status=dict(row.split(':',1) for row in (entry/'status').read_text().splitlines() if ':' in row)
            uids=list(map(int,status['Uid'].split())); nspid=list(map(int,status['NSpid'].split()))
            if len(set(uids))!=1 or not nspid:raise Refused('maintenance_process_unstable')
            if (stat_identity((entry/'stat').read_text())!=(ppid,ticks) or os.readlink(entry/'exe')!=exe
                    or (entry/'cmdline').read_bytes()!=raw or cgroups((entry/'cgroup').read_text())!=cg):
                raise Refused('maintenance_process_unstable')
            matches=[r for r in self.cfg['process_rules'] if r['exe']==exe and r['sha256']==digest and r['argv']==argv and r['uid']==uids[0]]
            if len(matches)!=1:raise Refused('maintenance_unmanaged_process')
            rows.append({'pid':int(entry.name),'ppid':ppid,'ticks':ticks,'nspid':nspid[-1],'rule':matches[0]['id']})
        by_pid={r['pid']:r for r in rows};rules={r['id']:r for r in self.cfg['process_rules']}
        if pid not in by_pid or rules[by_pid[pid]['rule']]['role']!='init':raise Refused('maintenance_init_unproven')
        for row in rows:
            if row['pid']==pid:continue
            parent=by_pid.get(row['ppid'])
            if parent is None or parent['rule'] not in rules[row['rule']]['parents']:
                raise Refused('maintenance_process_parent_invalid')
            visited=set();current=row
            while current['pid']!=pid:
                if current['pid'] in visited or current['ppid'] not in by_pid:
                    raise Refused('maintenance_process_parent_invalid')
                visited.add(current['pid']);current=by_pid[current['ppid']]
        return sorted(rows,key=lambda r:r['pid'])

    def resources(self):
        values={}
        for line in (self.proc/'meminfo').read_text().splitlines():
            if line.startswith(('MemAvailable:','SwapFree:')):
                name,value,unit=line.split()
                if unit!='kB':raise Refused('maintenance_resources_unknown')
                values[name[:-1]]=int(value)//1024
        if values.get('MemAvailable',0)<256 or values.get('SwapFree',0)<1536:
            raise Refused('maintenance_resources_low')
        return {'mem_available_mib':values['MemAvailable'],'swap_free_mib':values['SwapFree']}

    def __call__(self):
        started=self.clock();started_mono=self.monotonic();self.deadline=started_mono+20
        cfg=self.cfg;initial=self.inspect();states=self.components()
        for service in cfg['protected_services'].values():
            self.command(['systemctl','is-active','--quiet',service])
        self.resources()
        pvf=self.hash_file(cfg['pvf_path'],1024*1024*1024)
        program=self.hash_file(cfg['program_path'],128*1024*1024)
        if pvf!=cfg['pvf_sha256'] or program!=cfg['program_sha256']:
            raise Refused('maintenance_version_changed')
        rows=self.process_rows(initial['pid'])
        rules={r['id']:r for r in cfg['process_rules']};mysql=[r for r in rows if rules[r['rule']]['role']=='mysql']
        # Each retained supervisor must resolve to an observed, explicitly
        # approved process. A spoofed service PID cannot bless an extra writer.
        for name in cfg.get('resident_components',['mysql']):
            if name=='mysql':continue # separately verify daemon + ancestor chain below
            live=[r for r in rows if r['nspid']==states[name][-1]]
            roles={'logger'} if name.endswith('-log') else {'supervisor','mysql'}
            if len(live)!=1 or rules[live[0]['rule']]['role'] not in roles:
                raise Refused('maintenance_resident_process_unproven')
        service_pid=states['mysql'][-1]
        by_pid={r['pid']:r for r in rows}
        if len(mysql)!=1:raise Refused('maintenance_mysql_unproven')
        service_rows=[r for r in rows if r['nspid']==service_pid]
        if len(service_rows)!=1 or rules[service_rows[0]['rule']]['role'] not in ('mysql','supervisor'):
            raise Refused('maintenance_mysql_unproven')
        cursor=mysql[0]
        while cursor['nspid']!=service_pid:
            if cursor['pid']==initial['pid']:raise Refused('maintenance_mysql_unproven')
            cursor=by_pid[cursor['ppid']]
        if self.components()!=states or self.process_rows(initial['pid'])!=rows or self.inspect()!=initial:
            raise Refused('maintenance_probe_changed')
        metrics=self.resources();self.budget()
        return {**{k:v for k,v in initial.items() if k!='pid'},'components':list(cfg['components']),
                'boot_id':(self.proc/'sys/kernel/random/boot_id').read_text().strip(),
                'pvf_sha256':pvf,'program_sha256':program,'policy_sha256':self.policy_sha256,
                'process_set_sha256':hashlib.sha256(canonical(rows)).hexdigest(),
                'collected_at':started,'collected_monotonic':started_mono,'safe':True,'all_writers_down':True,'mysql_up':True,
                'non_game_core_ok':True,'no_unmanaged_processes':True,**metrics}
