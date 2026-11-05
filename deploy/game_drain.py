"""Fixed Qingfeng game drain adapter for the forthcoming web maintenance broker.

No HTTP/CLI entry point. The root broker must persist a reviewed plan and every
intent BEFORE invoking commands, with exclusive maintenance ownership. This module never sends SIGKILL to a game, `s6-svc -d`,
Docker stop/restart, systemctl mutations, or SQL. A completed drain is NOT a
maintenance permit: the full WindowManager quiescence proof is still required.
"""
import copy
import hashlib
import os
import re

from dnfgm.release_files import canonical, Refused
from inventory_probe import S6_SCRIPT, cgroups, in_container, read_components, stat_identity

# Static inspection of this exact on-disk program established SIGUSR2 -> suspend
# admission -> arrange_users -> shutdown-manager DB queues / thread joins.
# This is a protocol binding, NOT a claim of successful live/client validation.
PROGRAMS={'8859c99d8290dc5fb58151444138cf2697b2bfff12d47d6159596a03f20b5261':'qingfeng1031-usr2-drain-v1'}
TIMEOUT=180
DEPENDENCIES=('mysql','main_mysql_proxy','sg_mysql_proxy','dbmw_mnt','dbmw_stat','dbmw_guild','manager','monitor')


class Host:
    def __init__(self,probe):
        self.probe=probe
        self.cfg=probe.cfg

    def identity(self):
        p=self.probe;p.deadline=p.monotonic()+20
        identity=p.inspect()
        if p.hash_file(self.cfg['program_path'],128*1024*1024)!=self.cfg['program_sha256']:
            raise Refused('maintenance_version_changed')
        if p.hash_file(self.cfg['pvf_path'],1024*1024*1024)!=self.cfg['pvf_sha256']:
            raise Refused('maintenance_version_changed')
        for unit in self.cfg['protected_services'].values():
            p.command(['systemctl','is-active','--quiet',unit])
        p.resources()
        return {**identity,'boot_id':(p.proc/'sys/kernel/random/boot_id').read_text().strip(),
                'program_sha256':self.cfg['program_sha256'],'pvf_sha256':self.cfg['pvf_sha256'],
                'policy_sha256':p.policy_sha256}

    def services(self):
        self.probe.deadline=self.probe.monotonic()+20
        text=self.probe.command(['docker','exec',self.cfg['container'],'sh','-c',S6_SCRIPT])
        return read_components(text,self.cfg['components'])

    def game_process(self,identity,nspid):
        p=self.probe;p.deadline=p.monotonic()+20
        base=cgroups((p.proc/str(identity['pid'])/'cgroup').read_text())
        if all(v=='/' for v in base.values()):raise Refused('maintenance_container_not_isolated')
        ns=(p.proc/str(identity['pid'])/'ns/pid').stat().st_ino
        found=[];entries=list(p.proc.iterdir())
        if len(entries)>16384:raise Refused('maintenance_process_budget')
        for entry in entries:
            p.budget()
            if not entry.name.isdigit():continue
            try:
                cg=cgroups((entry/'cgroup').read_text())
                if not in_container(cg,base):continue
                status=dict(line.split(':',1) for line in (entry/'status').read_text().splitlines() if ':' in line)
                ids=list(map(int,status['NSpid'].split()))
                if not ids or ids[-1]!=nspid or (entry/'ns/pid').stat().st_ino!=ns:continue
                before=stat_identity((entry/'stat').read_text())
                exe=os.readlink(entry/'exe')
                if exe.endswith(' (deleted)') or p.hash_file(entry/'exe',128*1024*1024,proc_exe=True)!=identity['program_sha256']:
                    raise Refused('maintenance_game_program_mismatch')
                # A signal path absent from the running process is not inferred
                # solely from a same-named file in the container volume.
                if not int(status.get('SigCgt','0'),16)&(1<<(12-1)):
                    raise Refused('maintenance_shutdown_handler_missing')
                if (before!=stat_identity((entry/'stat').read_text()) or exe!=os.readlink(entry/'exe')
                        or cg!=cgroups((entry/'cgroup').read_text())):
                    raise Refused('maintenance_process_unstable')
                found.append({'pid':int(entry.name),'nspid':nspid,'start_ticks':before[1]})
            except FileNotFoundError:continue
        if len(found)!=1:raise Refused('maintenance_game_process_unproven')
        return found[0]

    def command(self,args,timeout=10):
        return self.probe.runner(args,timeout)

    def exit_result(self,container_id,service):
        text=self.command(['docker','exec',container_id,'s6-svstat','-o','exitcode,signum','/run/service/'+service])
        parts=text.split()
        if len(parts)!=2 or any(not re.fullmatch(r'-?[0-9]{1,3}',v) for v in parts):
            raise Refused('maintenance_exit_result_unknown')
        return tuple(map(int,parts))


class GameDrain:
    def __init__(self,host):self.host=host

    @staticmethod
    def dependencies(states):
        for name in DEPENDENCIES:
            row=states.get(name)
            if not row or row[:3]!=(True,True,True) or row[4]<1:
                raise Refused('maintenance_drain_storage_unavailable')
        return {name:list(states[name]) for name in DEPENDENCIES}

    def prepare(self):
        h=self.host;identity=h.identity();states=h.services();dependencies=self.dependencies(states)
        if identity['program_sha256'] not in PROGRAMS:raise Refused('maintenance_shutdown_protocol_unadapted')
        games=[n for n in h.cfg['components'] if n.startswith('game_') and n!='game_template']
        if not 1<=len(games)<=16 or any(not re.fullmatch(r'game_[a-zA-Z0-9_]{1,48}',n) for n in games):
            raise Refused('maintenance_game_set_unadapted')
        active=[]
        for name in games:
            row=states[name]
            if row[0] and row[1] and row[2] and row[4]>0:
                active.append({'service':name,'before':list(row),'process':h.game_process(identity,row[4])})
            elif row[0] or row[1] or row[4]!=-1:raise Refused('maintenance_game_state_unstable')
        plan={'version':1,'identity':identity,'protocol':PROGRAMS[identity['program_sha256']],
              'games':active,'components':list(h.cfg['components']),'dependencies':dependencies,
              'warning':'将断开游戏内玩家并等待存档退出；超时不强杀、不自动重发。'}
        plan['fingerprint']=hashlib.sha256(canonical(plan)).hexdigest()
        return plan

    def execute(self,plan,record):
        """Consume exactly once; `record` must durably reserve each intent.

        On any exception the caller retains the original plan/intent and queries
        actual state. It must NOT call execute again or automatically reopen login.
        """
        expected=copy.deepcopy(plan)
        if self.prepare()!=expected:raise Refused('maintenance_drain_preview_changed')
        if not callable(record):raise Refused('maintenance_durable_recorder_required')
        h=self.host;cid=expected['identity']['container_id']
        record('drain-started',{'fingerprint':expected['fingerprint']})
        for game in expected['games']:
            name=game['service'];directory='/run/service/'+name
            if h.identity()!=expected['identity'] or h.game_process(expected['identity'],game['before'][4])!=game['process']:
                raise Refused('maintenance_drain_target_changed')
            # Never use -D: this image configures game's down-signal as SIGKILL.
            # -O inhibits supervisor restart without terminating the live game.
            # The down marker also inhibits restart after a supervisor failure.
            record('inhibit-intent',{'service':name})
            h.command(['docker','exec',cid,'s6-svc','-O',directory])
            h.command(['docker','exec',cid,'touch',directory+'/down'])
            current_states=h.services();current=current_states[name]
            if self.dependencies(current_states)!=expected['dependencies']:
                raise Refused('maintenance_drain_dependencies_changed')
            if current!=(True,False,False,game['before'][3],game['before'][4]):
                raise Refused('maintenance_drain_target_changed')
            if h.game_process(expected['identity'],current[4])!=game['process']:
                raise Refused('maintenance_drain_target_changed')
            record('signal-intent',{'service':name,'signal':'SIGUSR2'})
            h.command(['docker','exec',cid,'s6-svc','-2',directory])
            record('signal-sent',{'service':name})
            # Wait only. A timeout leaves the game draining and authority closed.
            h.command(['docker','exec',cid,'s6-svwait','-D','-t',str(TIMEOUT*1000),directory],TIMEOUT+5)
            final_states=h.services()
            if self.dependencies(final_states)!=expected['dependencies']:
                raise Refused('maintenance_drain_dependencies_changed')
            if h.identity()!=expected['identity'] or final_states[name]!=(False,False,False,True,-1):
                raise Refused('maintenance_drain_not_complete')
            # s6 may print 0 or -1 for a normal non-signalled exit, by version.
            exit_code,signum=h.exit_result(cid,name)
            if exit_code!=0 or signum not in (0,-1):raise Refused('maintenance_game_exit_abnormal')
            record('game-drained',{'service':name,'exit_code':exit_code,'signum':signum})
        result={'state':'game_drained','fingerprint':expected['fingerprint'],
                'services':[g['service'] for g in expected['games']],
                'maintenance_permit':False,'client_verified':False}
        record('drain-finished',result)
        return result
