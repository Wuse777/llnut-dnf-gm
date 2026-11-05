"""Fixed Qingfeng auxiliary writer stop/restore adapter, never a command API.

Plans are root-generated and bind original service flags, live processes and
startup contracts. Game drain MUST precede stop(); a closed/reconciled window
MUST precede restore(). Caller durably journals every intent and never replays
an uncertain command. MySQL/log/s6 residents and originally dormant services
are NEVER started/stopped. This adapter never opens a write gate or a permit.
"""
import copy
import os
import re
import time

from dnfgm.release_files import Refused
from game_drain import Host, PROGRAMS
from inventory_probe import cgroups, in_container, stat_identity

# Static evidence: auction/point SIGUSR2 -> SetStopReceived -> periodic work/DB
# queue checks; community SIGUSR2 sets its shutdown flag. These are exact binary
# protocols, not live/client validation. Never substitute default SIGKILL.
GRACEFUL = {
    'auction': 'd505d6b675a1a1b9f18287195d0f769c554b4940359ec8a16d08e8538b231a5a',
    'point': 'd79917494b7bb47d824b8cb869c2f6657b385f280c862b8539eea99e09174da7',
    'community': 'fe1b06e880218fc0ed89c011506aef59b46e0322b999e54a3ebd741c238b8a1e',
}
# Dependencies stay alive until their consumers exit. Gateway/scheduler stay
# last on restore so new activity is not admitted before the game is ready.
STOP_ORDER = ('llnut_gate', 'scheduler', 'auction', 'point', 'community', 'guild',
              'channel', 'bridge', 'coserver', 'relay', 'statics', 'gunnersvr',
              'zergsvr_secagent', 'zergsvr', 'stun', 'monitor_ip', 'monitor',
              'manager', 'dbmw_guild', 'dbmw_stat', 'dbmw_mnt', 'sg_mysql_proxy',
              'main_mysql_proxy')
INFRA = {'mysql', 's6-linux-init-shutdownd', 's6rc-fdholder', 's6rc-oneshot-runner'}
DORMANT = {'game_template', 'netbird', 'tailscale', 'tailscaled'}
STOP_TIMEOUT = 180
START_TIMEOUT = 180
FILES = ('run', 'finish', 'run.user', 'finish.user', 'down-signal', 'timeout-kill',
         'timeout-finish', 'notification-fd', 'startup', 'on-start', 'runprobe')
SETTINGS = ('down-signal', 'timeout-kill', 'timeout-finish', 'notification-fd')
SPECIAL_STARTUP = {
    'llnut_gate': '/home/template/init/run/start_gate.sh',
    'scheduler': '/home/template/init/scheduler/scheduler.sh',
    'monitor_ip': '/home/template/init/monitor_ip/monitor_ip.sh',
    'main_mysql_proxy': '/home/template/init/mysql_proxy/start_main_mysql_proxy.sh',
    'sg_mysql_proxy': '/home/template/init/mysql_proxy/start_mysql_proxy.sh',
}
CONTRACT_SCRIPT = r'''set -eu
for n in run finish run.user finish.user down-signal timeout-kill timeout-finish notification-fd startup on-start runprobe; do
 case "$n" in
  startup) f="$2";;
  on-start) f=/etc/s6-overlay/scripts/on-start;;
  runprobe) f=/home/template/init/lib/s6-runprobe;;
  *) f="$1/$n";;
 esac
 printf '%s=' "$n"
 if test -f "$f"; then sha256sum "$f" | cut -d' ' -f1; else printf 'absent\n'; fi
done
for n in down-signal timeout-kill timeout-finish notification-fd; do
 printf 'value-%s=' "$n"
 if test -f "$1/$n"; then head -c 64 "$1/$n"; fi
 printf '\n'
done'''


def is_game(name):
    return isinstance(name, str) and name != 'game_template' and re.fullmatch(r'game_[a-zA-Z0-9_]{1,48}', name) is not None


def checked_name(name):
    if name not in STOP_ORDER and not is_game(name):
        raise Refused('maintenance_service_unadapted')
    return name


def parse_contract(text):
    if not isinstance(text, str) or len(text) > 8192:
        raise Refused('maintenance_service_contract_invalid')
    values = {}
    for line in text.splitlines():
        if not line:continue  # Files usually contain a final LF before printf.
        key, sep, value = line.partition('=')
        if not sep or key in values:
            raise Refused('maintenance_service_contract_invalid')
        values[key] = value
    if set(values) != set(FILES) | {'value-' + n for n in SETTINGS}:
        raise Refused('maintenance_service_contract_invalid')
    for name in FILES:
        if values[name] != 'absent' and not re.fullmatch(r'[a-f0-9]{64}', values[name]):
            raise Refused('maintenance_service_contract_invalid')
    if any(values[n] == 'absent' for n in ('run', 'run.user', 'startup', 'on-start')):
        raise Refused('maintenance_service_contract_incomplete')
    for name in SETTINGS:
        value = values['value-' + name]
        if name == 'down-signal':
            if value not in ('', 'SIGTERM', 'SIGUSR2', 'SIGKILL'):
                raise Refused('maintenance_service_signal_unadapted')
        elif value and not re.fullmatch(r'[0-9]{1,9}', value):
            raise Refused('maintenance_service_contract_invalid')
        if (values[name] == 'absent') != (value == ''):
            raise Refused('maintenance_service_contract_invalid')
    return values


class ServiceHost(Host):
    def contract(self, identity, name):
        checked_name(name)
        startup = SPECIAL_STARTUP.get(name, '/data/run/start_' + ('game' if is_game(name) else name) + '.sh')
        text = self.command(['docker', 'exec', identity['container_id'], 'sh', '-c',
                             CONTRACT_SCRIPT, 'dnfgm-contract', '/run/service/' + name, startup])
        return parse_contract(text)

    def service_process(self, identity, nspid):
        p = self.probe;p.deadline = p.monotonic() + 20
        base = cgroups((p.proc / str(identity['pid']) / 'cgroup').read_text())
        if all(v == '/' for v in base.values()):
            raise Refused('maintenance_container_not_isolated')
        ns = (p.proc / str(identity['pid']) / 'ns/pid').stat().st_ino
        found = []; entries = list(p.proc.iterdir())
        if len(entries) > 16384:raise Refused('maintenance_process_budget')
        for entry in entries:
            p.budget()
            if not entry.name.isdigit():continue
            try:
                cg = cgroups((entry / 'cgroup').read_text())
                if not in_container(cg, base):continue
                status = dict(line.split(':', 1) for line in (entry / 'status').read_text().splitlines() if ':' in line)
                ids = list(map(int, status['NSpid'].split()))
                if not ids or ids[-1] != nspid or (entry / 'ns/pid').stat().st_ino != ns:continue
                before = stat_identity((entry / 'stat').read_text())
                exe = os.readlink(entry / 'exe')
                if exe.endswith(' (deleted)'):raise Refused('maintenance_service_program_changed')
                sha = p.hash_file(entry / 'exe', 128 * 1024 * 1024, proc_exe=True)
                caught, ignored = int(status['SigCgt'], 16), int(status['SigIgn'], 16)
                after_status = dict(line.split(':', 1) for line in (entry / 'status').read_text().splitlines() if ':' in line)
                if (before != stat_identity((entry / 'stat').read_text()) or exe != os.readlink(entry / 'exe')
                        or cg != cgroups((entry / 'cgroup').read_text())
                        or (entry / 'ns/pid').stat().st_ino != ns
                        or any(status[k] != after_status.get(k) for k in ('NSpid', 'SigCgt', 'SigIgn'))):
                    raise Refused('maintenance_process_unstable')
                found.append({'pid': int(entry.name), 'nspid': nspid, 'start_ticks': before[1],
                              'program_sha256': sha, 'caught': caught, 'ignored': ignored})
            except (FileNotFoundError, ProcessLookupError):continue
        if len(found) != 1:raise Refused('maintenance_service_process_unproven')
        return found[0]


def signal_for(name, process, contract):
    if name in GRACEFUL or is_game(name):
        expected = GRACEFUL.get(name)
        if (expected and process['program_sha256'] != expected or
                is_game(name) and process['program_sha256'] not in PROGRAMS or
                not process['caught'] & (1 << 11)):
            raise Refused('maintenance_service_shutdown_unadapted')
        return 'SIGUSR2'
    if contract['value-down-signal'] not in ('', 'SIGTERM') or process['ignored'] & (1 << 14):
        raise Refused('maintenance_service_shutdown_unadapted')
    return 'SIGTERM'


def down(row):
    return tuple(row) == (False, False, False, True, -1)


class ServiceLifecycle:
    def __init__(self, host, *, sleep=time.sleep, monotonic=time.monotonic):
        self.host,self.sleep,self.monotonic = host,sleep,monotonic

    def prepare(self, game_plan):
        h = self.host;identity = game_plan['identity'];before = game_plan['services_before']
        if h.identity() != identity or {k:list(v) for k,v in h.services().items()} != before:
            raise Refused('maintenance_services_changed')
        residents = set(h.cfg.get('resident_components', ['mysql']))
        dormant = set(h.cfg.get('dormant_components', []))
        if (not residents <= set(before) or not dormant <= DORMANT or not dormant <= set(before)
                or residents & dormant or 'mysql' not in residents
                or any(n not in INFRA and not n.endswith('-log') for n in residents)):
            raise Refused('maintenance_service_policy_invalid')
        candidates = set(before) - residents - dormant
        if any(n not in STOP_ORDER and not is_game(n) for n in candidates):
            raise Refused('maintenance_service_set_unadapted')
        for name in residents:
            row = before[name]
            if not row[0] or not row[1] or row[4] <= 0:
                raise Refused('maintenance_resident_not_running')
        for name in dormant:
            row = before[name]
            if row[0] or row[1] or row[4] != -1:
                raise Refused('maintenance_dormant_running')
        entries = {}
        for name in sorted(candidates):
            row = before[name]
            if not row[0] and not row[1] and row[4] == -1:
                continue  # Originally down components stay down, without editing flags.
            if not row[0] or not row[1] or row[4] <= 0:
                raise Refused('maintenance_service_state_unstable')
            process = h.service_process(identity, row[4]); contract = h.contract(identity, name)
            if contract['notification-fd'] != 'absent' and not row[3]:
                raise Refused('maintenance_service_not_ready')
            entries[name] = {'before': list(row), 'process': process, 'contract': contract,
                             'signal': signal_for(name, process, contract)}
        games = [g['service'] for g in game_plan['games']]
        if set(games) != {n for n in entries if is_game(n)}:
            raise Refused('maintenance_game_plan_mismatch')
        stop = [n for n in STOP_ORDER if n in entries]
        start = [n for n in reversed(stop) if n not in ('scheduler', 'llnut_gate')] + games + [n for n in ('scheduler', 'llnut_gate') if n in entries]
        result = {'version': 1, 'entries': entries, 'games': games, 'stop_order': stop, 'start_order': start,
                  'unchanged': sorted(set(before) - set(entries))}
        if h.identity() != identity or {k:list(v) for k,v in h.services().items()} != before:
            raise Refused('maintenance_services_changed')
        return result

    def check(self, plan, expected, *, target=None, original_process=False):
        h = self.host;identity = plan['identity']
        if h.identity() != identity or {k:list(v) for k,v in h.services().items()} != expected:
            raise Refused('maintenance_services_changed')
        if target is not None:
            entry = plan['service_cycle']['entries'][target]
            if h.contract(identity, target) != entry['contract']:
                raise Refused('maintenance_service_contract_changed')
            if original_process and h.service_process(identity, entry['before'][4]) != entry['process']:
                raise Refused('maintenance_service_process_changed')

    def settle(self, plan, previous, expected, target):
        # s6-svc writes a FIFO; command return is not acknowledgement that
        # wantedup changed. Tolerate ONLY the exact previous state briefly.
        deadline=self.monotonic()+2
        while True:
            states={k:list(v) for k,v in self.host.services().items()}
            if states==expected:
                self.check(plan,expected,target=target)
                return
            if states!=previous or self.monotonic()>=deadline:
                raise Refused('maintenance_service_transition_unproven')
            self.sleep(.05)

    def stopped_snapshot(self, plan):
        expected = copy.deepcopy(plan['services_before'])
        for name in plan['service_cycle']['entries']:
            expected[name] = [False, False, False, True, -1]
        return expected

    def stop(self, plan, record):
        if not callable(record):raise Refused('maintenance_durable_recorder_required')
        h = self.host;cycle = validate_cycle(plan);cid = plan['identity']['container_id']
        expected = copy.deepcopy(plan['services_before'])
        for name in cycle['games']:expected[name] = [False, False, False, True, -1]
        self.check(plan, expected)
        record('writers-stop-started', {'services': cycle['stop_order']})
        for name in cycle['stop_order']:
            entry = cycle['entries'][name];directory = '/run/service/' + checked_name(name)
            self.check(plan, expected, target=name, original_process=True)
            record('writer-inhibit-intent', {'service': name})
            h.command(['docker','exec',cid,'s6-svc','-O',directory])
            previous=copy.deepcopy(expected);expected[name][1] = False
            self.settle(plan,previous,expected,name);self.check(plan, expected, target=name, original_process=True)
            record('writer-inhibit-applied', {'service': name})
            record('writer-marker-intent', {'service': name})
            h.command(['docker','exec',cid,'touch',directory+'/down'])
            previous=copy.deepcopy(expected);expected[name][2] = False
            self.settle(plan,previous,expected,name);self.check(plan, expected, target=name, original_process=True)
            record('writer-marker-applied', {'service': name})
            record('writer-signal-intent', {'service': name, 'signal': entry['signal']})
            h.command(['docker','exec',cid,'s6-svc','-2' if entry['signal']=='SIGUSR2' else '-t',directory])
            record('writer-signal-sent', {'service': name})
            h.command(['docker','exec',cid,'s6-svwait','-D','-t',str(STOP_TIMEOUT*1000),directory],STOP_TIMEOUT+5)
            code, signum = h.exit_result(cid,name)
            normal = code == 0 and signum in (0,-1)
            # Direct TERM exit is valid only for the explicitly selected TERM
            # protocol; USR2 components must finish normally, never via SIGKILL.
            terminated = entry['signal']=='SIGTERM' and code==256 and signum==15
            if not normal and not terminated:raise Refused('maintenance_writer_exit_abnormal')
            expected[name] = [False,False,False,True,-1]
            self.check(plan,expected)
            record('writer-stopped', {'service':name,'exit_code':code,'signum':signum})
        self.check(plan,self.stopped_snapshot(plan))
        record('writers-stopped', {'services':cycle['stop_order'],'maintenance_permit':False})

    def observe(self, plan, events):
        """Read-only snapshot bound to the durable per-service intent prefix."""
        cycle=validate_cycle(plan);h=self.host;identity=plan['identity']
        if h.identity()!=identity:raise Refused('maintenance_services_changed')
        states=h.services();before=plan['services_before']
        if set(states)!=set(before) or any(list(states[n])!=before[n] for n in cycle['unchanged']):
            raise Refused('maintenance_unchanged_service_changed')
        phases={}
        for event in events:
            if event['data'].get('service') in cycle['entries']:
                phases[event['data']['service']]=event['phase'].removeprefix('writer-')
        observed=[]
        for name,entry in cycle['entries'].items():
            row=states[name];original=entry['before'];phase=phases.get(name)
            state='changed'
            if h.contract(identity,name)!=entry['contract']:
                raise Refused('maintenance_service_contract_changed')
            if list(row)==original and phase in (None, 'inhibit-intent'):
                state='original'
            elif row[0] and row[4]==original[4] and row[3]==original[3]:
                if not row[1] and row[2]==original[2] and phase in ('inhibit-intent','inhibit-applied','marker-intent'):
                    state='restart_inhibited_marker_missing'
                elif not row[1] and not row[2] and phase in ('marker-intent','marker-applied','signal-intent','signal-sent'):
                    state='restart_inhibited'
            elif down(row) and phase in ('signal-intent','signal-sent','stopped','game-drained'):
                code,signum=h.exit_result(identity['container_id'],name)
                if code==0 and signum in (0,-1):state='down_normal'
                elif entry['signal']=='SIGTERM' and code==256 and signum==15:state='down_terminated'
                else:state='down_abnormal'
            if row[0] and h.service_process(identity,row[4])!=entry['process']:
                state='changed'
            observed.append({'service':name,'state':state})
        if h.identity()!=identity or h.services()!=states:raise Refused('maintenance_observation_changed')
        return observed

    def restore(self, plan, record, check_closed, *, events=()):
        """Continue an explicit restore from a validated durable event prefix.

        A persisted start intent is never sent twice. If its effect cannot be
        observed as the expected live process, retain the freeze for inspection.
        Only harmless startup-marker writes can be reconciled idempotently.
        """
        if not callable(record) or not callable(check_closed):raise Refused('maintenance_restore_authority_required')
        h=self.host;cycle=validate_cycle(plan);identity=plan['identity'];cid=identity['container_id']
        latest={e['data']['service']:e for e in events if 'service' in e['data']}
        expected=self.stopped_snapshot(plan)
        # Reconstruct all already-started services before any new command. This
        # also rejects unexpected starts of a later service or changed processes.
        for name,entry in cycle['entries'].items():
            event=latest.get(name);phase=event['phase'] if event else None
            if phase=='service-restored':
                expected[name]=event['data']['state']
                if h.service_process(identity,expected[name][4])!=event['data']['process']:
                    raise Refused('maintenance_restored_process_changed')
            elif phase:
                actual=list(h.services()[name]);marked=[False,False,entry['before'][2],True,-1]
                if phase=='restore-marker-intent':
                    if actual not in (expected[name],marked):raise Refused('maintenance_restore_unexpected_state')
                elif phase=='restore-marker-applied':
                    if actual!=marked:raise Refused('maintenance_restore_unexpected_state')
                elif phase in ('restore-start-intent','restore-start-sent'):
                    if (not actual[0] or not actual[1] or actual[2]!=entry['before'][2] or actual[4]<=0):
                        raise Refused('maintenance_start_outcome_unproven')
                    if h.service_process(identity,actual[4])['program_sha256']!=entry['process']['program_sha256']:
                        raise Refused('maintenance_restored_program_changed')
                else:raise Refused('maintenance_session_transition_invalid')
                expected[name]=actual
        self.check(plan,expected)
        for name in cycle['start_order']:
            if check_closed() is not True:raise Refused('maintenance_close_not_proven')
            entry=cycle['entries'][name];directory='/run/service/'+checked_name(name)
            event=latest.get(name);phase=event['phase'] if event else None
            if phase=='service-restored':continue
            self.check(plan,expected,target=name)
            if phase is None:
                record('restore-marker-intent',{'service':name,'normally_up':entry['before'][2]})
                phase='restore-marker-intent'
            if phase=='restore-marker-intent':
                if expected[name][2]!=entry['before'][2]:
                    if entry['before'][2]:h.command(['docker','exec',cid,'rm','-f','--',directory+'/down'])
                    else:h.command(['docker','exec',cid,'touch',directory+'/down'])
                    previous=copy.deepcopy(expected);expected[name][2]=entry['before'][2]
                    self.settle(plan,previous,expected,name)
                record('restore-marker-applied',{'service':name});phase='restore-marker-applied'
            if phase=='restore-marker-applied':
                if check_closed() is not True:raise Refused('maintenance_close_not_proven')
                record('restore-start-intent',{'service':name})
                h.command(['docker','exec',cid,'s6-svc','-u',directory])
                record('restore-start-sent',{'service':name})
            elif phase=='restore-start-intent':
                # A matching running process proves the required state, not that
                # a lost command response arrived. No new start is issued here.
                record('restore-start-sent',{'service':name,'reconciled':True})
            wait='-U' if entry['contract']['notification-fd']!='absent' else '-u'
            h.command(['docker','exec',cid,'s6-svwait',wait,'-t',str(START_TIMEOUT*1000),directory],START_TIMEOUT+5)
            actual=h.services()[name]
            if (not actual[0] or not actual[1] or actual[2]!=entry['before'][2] or actual[4]<=0
                    or wait=='-U' and not actual[3]):raise Refused('maintenance_restored_service_not_ready')
            process=h.service_process(identity,actual[4])
            if process['program_sha256']!=entry['process']['program_sha256']:
                raise Refused('maintenance_restored_program_changed')
            expected[name]=list(actual);self.check(plan,expected,target=name)
            record('service-restored',{'service':name,'process':process,'state':list(actual)})
        if check_closed() is not True:raise Refused('maintenance_close_not_proven')
        self.check(plan,expected)
        if not any(e['phase']=='services-restored' for e in events):
            record('services-restored',{'services':cycle['start_order'],'ordinary_writes_open':False})
        return expected


def validate_cycle(plan):
    """Validate durable plan shape/order; no host reads or commands."""
    try:
        cycle=plan['service_cycle'];before=plan['services_before'];entries=cycle['entries']
        if (not isinstance(cycle,dict) or set(cycle)!={'version','entries','games','stop_order','start_order','unchanged'}
                or type(cycle['version']) is not int or cycle['version']!=1 or not isinstance(entries,dict)
                or not set(entries)<=set(before)):
            raise ValueError()
        games=[g['service'] for g in plan['games']]
        if cycle['games']!=games or set(games)!={n for n in entries if is_game(n)}:raise ValueError()
        stop=[n for n in STOP_ORDER if n in entries]
        start=[n for n in reversed(stop) if n not in ('scheduler','llnut_gate')]+games+[n for n in ('scheduler','llnut_gate') if n in entries]
        if (cycle['stop_order']!=stop or cycle['start_order']!=start or len(start)!=len(entries)
                or cycle['unchanged']!=sorted(set(before)-set(entries))):raise ValueError()
        for name,entry in entries.items():
            checked_name(name)
            if set(entry)!={'before','process','contract','signal'} or entry['before']!=before[name]:raise ValueError()
            row=entry['before'];process=entry['process'];contract=entry['contract']
            if (len(row)!=5 or any(type(x) is not bool for x in row[:4]) or type(row[4]) is not int
                    or not row[0] or not row[1] or row[4]<=0):raise ValueError()
            if (set(process)!={'pid','nspid','start_ticks','program_sha256','caught','ignored'}
                    or any(type(process[k]) is not int or process[k]<0 for k in ('pid','nspid','start_ticks','caught','ignored'))
                    or process['pid']<=1 or process['nspid']!=row[4]
                    or not isinstance(process['program_sha256'],str) or not re.fullmatch('[a-f0-9]{64}',process['program_sha256'])):raise ValueError()
            if parse_contract('\n'.join(k+'='+v for k,v in contract.items()))!=contract:raise ValueError()
            if signal_for(name,process,contract)!=entry['signal']:raise ValueError()
        return cycle
    except (KeyError,TypeError,ValueError,AttributeError):
        raise Refused('maintenance_service_plan_invalid') from None


def stop_steps(plan):
    cycle=validate_cycle(plan)
    steps=[('writers-stop-started',{'services':cycle['stop_order']})]
    for name in cycle['stop_order']:
        item={'service':name}
        steps.extend((phase,item) for phase in ('writer-inhibit-intent','writer-inhibit-applied','writer-marker-intent','writer-marker-applied'))
        steps.extend([('writer-signal-intent',{**item,'signal':cycle['entries'][name]['signal']}),
                      ('writer-signal-sent',item),('writer-stopped',{**item,'signal':cycle['entries'][name]['signal']})])
    steps.append(('writers-stopped',{'services':cycle['stop_order'],'maintenance_permit':False}))
    return steps
