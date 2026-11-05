"""Admin-only capability inventory. No activation, game query packets or writes.

Configured switches, observed prerequisites and human-recorded validation are
separate facts. This endpoint must never be used as permission to execute.
"""
from contextlib import closing
import json
import math
from pathlib import Path
import re
import time

from . import __version__
from .catalog import Catalog, snapshot

SHA = re.compile(r'^[a-f0-9]{64}$')
IMAGE = re.compile(r'^sha256:[a-f0-9]{64}$')
REVISION = re.compile(r'^[a-f0-9]{7,40}(?:-dirty)?$')
REFERENCE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}$')
REQUIRED_SCHEMA = set(range(1, 14))
# id, label, group, destination, activation switch, extra prerequisite note
FEATURES = (
 ('maintenance','网页维护申请与执行记录','装备维护','maintenance','maintenance','退出会断开玩家；须具备完整退出、关窗与恢复执行器。入队或游戏退出不等于维护许可。'),
 ('players','玩家中心与角色存档','玩家管理','accounts',None,'角色属性是数据库存档，不是实时战斗属性。'),
 ('currency','点券／代币券／积分','奖励运营','accounts','currency','最终余额及在线消费一致性仍由对应操作校验和验收确认。'),
 ('mail','物品与金币邮件','奖励运营','mail','mail','领取标记不等于背包验收；每种特殊附件应独立核验。'),
 ('templates','版本化礼包模板','奖励运营','gifts',None,'模板可编辑不代表奖励写入开关已启用。'),
 ('reward','账号与角色组合奖励','奖励运营','mail','reward','实际组合还需开启currency和／或mail，不是单凭reward开关执行。'),
 ('batch-reward','账号／角色名单批量奖励','奖励运营','reward-jobs','batch-reward','具体奖励需要相应写入开关，任务须明确确认；按收件人事务执行。'),
 ('schedules','定时奖励与公告','奖励运营','schedules','schedules','每种任务仍需自己的执行器和写入开关；不会因为启用计划就补发错过期次。'),
 ('ban','封禁','玩家管理','accounts','ban','只管理本后台处罚，默认不立即踢出在线玩家。'),
 ('unban','解封','玩家管理','accounts','unban','不覆盖其他来源处罚；游戏登录效果需独立核验。'),
 ('equipment-unlock','装备提前解锁','玩家管理','unlock-center','equipment-unlock','仅将申请设为到期，游戏加载处理与数据库修改分开判断。'),
 ('native-session','原生会话查询','在线控制','online','native-session','本页不发送探测包；请在玩家页核验原生程序指纹及实时响应。'),
 ('native-notice','原生公告','在线控制','native-controls','native-notice','需要原生协议、程序指纹及资源门槛；发包结果不是玩家已看到。'),
 ('native-kick','踢下线','在线控制','native-controls','native-kick','需要原生程序指纹和目标会话；本页不查询或踢出任何账号。'),
 ('native-ban-kick','封禁并踢下线','在线控制','native-controls','native-ban-kick','处罚事务与原生控制结果分别记录，不能假设跨系统原子成功。'),
 ('item-edit','装备属性与数量编辑','装备维护','accounts','item-edit','必须先显式进入维护窗口，并校验程序指纹、容器原始存档和字段语义。'),
 ('item-reclaim','指定物品实例回收','装备维护','accounts','item-reclaim','维护窗口中核对整个存档，不按物品编号盲目删除多个实例。'),
 ('item-restore','装备存档快照恢复','装备维护','accounts','item-restore','仅在当前存档与原操作after-image完全一致时恢复，不覆盖后续游戏进度。'),
 ('char-fatigue','角色疲劳恢复／调整','角色维护','accounts','char-fatigue','仅在显式维护窗口修改普通／额外已消耗疲劳，0表示恢复；历史计数与上限不变。'),
 ('mail-center','完整邮件与操作追踪','记录与维护','mail-center',None,'区分已投递、数据库领取标记与记录缺失。'),
 ('support','玩家问题工作台','记录与维护','support',None,'补偿草稿需再次预览确认，不等于直接撤销原操作。'),
 ('economy','GM发放统计','记录与维护','economy',None,'只统计可覆盖的GM操作，不冒充全服完整经济流水。'),
 ('compatibility','升级引用检查','记录与维护','compatibility',None,'只读核对候选资源，不自动激活PVF或暂停任务。'),
 ('assets','物品图标与职业头像','展示与素材','catalog','assets','图片包匹配不代表像素或客户端一致性已验收。'),
 ('private-message','指定玩家系统消息','待适配',None,'unimplemented','尚未接入当前镜像可靠的私信通道。'),
 ('character-rescue','位置救援／改名等角色维护','待适配',None,'unimplemented','存档字段、在线缓存与合法组合仍待适配，不能任意改字段上线。'),
)
REASONS = {
 'maintenance_executor_missing':'完整维护执行与恢复执行器尚未安装或状态过期，可在维护中心核对；不是管理员权限限制。',
 'disabled':'配置开关未启用', 'unimplemented':'尚未实现当前镜像适配',
 'schema_unknown':'无法确认管理库迁移状态', 'schema_missing':'管理库迁移不完整',
 'snapshot_unknown':'实时采集缺失或已过期', 'core_unknown':'核心服务本次未确认健康',
 'binding_unknown':'没有有效的镜像／PVF绑定', 'binding_mismatch':'实时镜像／PVF与配置不匹配',
 'resource_unknown':'资源数据缺失或低于保护阈值', 'catalog_unknown':'只读物品索引不可用',
 'catalog_mismatch':'物品索引与配置PVF不匹配', 'worker_disabled':'批量执行器未启用',
 'assets_unknown':'匹配图片包尚未可用', 'activation_missing':'缺少显式能力激活记录',
}


def release_identity():
    root = Path(__file__).resolve().parents[2]
    try:
        with (root/'SOURCE_REVISION').open() as f:
            value = f.read(128).strip()
        revision = value if REVISION.fullmatch(value) else None
    except OSError:
        revision = None
    return {'version':__version__, 'source_revision':revision,
            'source_state':'unknown' if revision is None else 'dirty' if revision.endswith('-dirty') else 'recorded'}


def evidence(path, binding, now):
    """Private maintenance attestations, never inferred from enabled booleans."""
    if not path:
        return {'state':'not_configured','records':{}}
    try:
        with Path(path).open('rb') as f:
            raw=f.read(65537)
        if len(raw)>65536:raise ValueError()
        data=json.loads(raw)
        records=data.get('records')
        if data.get('schema_version')!=1 or not isinstance(records,list) or len(records)>64:raise ValueError()
        result={};known={f[0] for f in FEATURES}
        for row in records:
            if not isinstance(row,dict):raise ValueError()
            key=row.get('capability');checked=row.get('checked_at');reference=row.get('reference')
            if (key not in known or key in result or row.get('level') not in ('api','client')
                or type(checked) not in (int,float) or not math.isfinite(checked) or not 0<checked<=now+5
                or not isinstance(reference,str) or not REFERENCE.fullmatch(reference)):
                raise ValueError()
            matched=all(binding.get(k) and row.get(k)==binding[k] for k in ('source_revision','pvf_sha256','image_digest'))
            matched=matched and not str(binding.get('source_revision','')).endswith('-dirty')
            result[key]={'state':'matched' if matched else 'version_mismatch', 'level':row['level'],
                         'checked_at':checked,'reference':reference}
        return {'state':'loaded','records':result}
    except (OSError,ValueError,TypeError,AttributeError):
        return {'state':'unavailable','records':{}}


def report(settings, db):
    now=time.time();live=snapshot(settings);release=release_identity();catalog=Catalog(settings)
    collected=live.get('collected_at')
    if type(collected) not in (int,float) or not math.isfinite(collected):
        live={**live,'fresh':False,'collected_at':None}
    versions=[];schema_state='unknown'
    try:
        with db.connect() as c,c.cursor() as q:
            q.execute('SELECT version FROM dnf_gm.schema_versions ORDER BY version LIMIT 33')
            versions=[r['version'] for r in q.fetchall()]
        if len(versions)>32 or any(type(v) is not int for v in versions):raise ValueError()
        schema_state='ok' if REQUIRED_SCHEMA<=set(versions) else 'incomplete'
    except Exception:
        versions=[]
    catalog_sha=None;catalog_state='unavailable'
    try:
        with closing(catalog.connect()) as c:
            row=c.execute("SELECT value FROM metadata WHERE key='pvf_sha256'").fetchone()
            if row and isinstance(row[0],str) and SHA.fullmatch(row[0]):
                catalog_sha=row[0];catalog_state='matched' if row[0]==settings.pvf_sha256 else 'mismatch'
    except Exception:
        pass
    try:
        raw_assets=catalog.assets.status(settings.pvf_sha256)
        asset_state=raw_assets.get('state') if raw_assets.get('state') in ('ready','not_installed','unavailable','mismatch') else 'unavailable'
    except Exception:
        asset_state='unavailable'
    pvf=settings.pvf_sha256 if SHA.fullmatch(settings.pvf_sha256) else None
    image=settings.image_digest if IMAGE.fullmatch(settings.image_digest) else None
    binding={'source_revision':release['source_revision'],'pvf_sha256':pvf,'image_digest':image}
    recorded=evidence(settings.capability_evidence_file,binding,now)
    schema_errors=[] if schema_state=='ok' else ['schema_missing' if schema_state=='incomplete' else 'schema_unknown']
    write_errors=list(schema_errors)
    if not live.get('fresh'):write_errors.append('snapshot_unknown')
    else:
        if live.get('core_ok') is not True:write_errors.append('core_unknown')
        if pvf and image and (live.get('pvf_sha256')!=pvf or live.get('image_digest')!=image):write_errors.append('binding_mismatch')
        values=((live.get('mem_available_mib'),256),(live.get('swap_free_mib'),1536))
        if any(type(v) not in (int,float) or not math.isfinite(v) or v<minimum for v,minimum in values):write_errors.append('resource_unknown')
    if not pvf or not image:write_errors.append('binding_unknown')
    rows=[]
    for key,label,group,destination,switch,note in FEATURES:
        enabled=True;errors=[];implemented=switch!='unimplemented'
        if switch=='unimplemented':enabled=False;errors=['unimplemented']
        elif switch=='assets':enabled=bool(settings.assets_dir);errors=[] if asset_state=='ready' else ['assets_unknown']
        elif switch=='schedules':enabled=settings.schedule_worker_enabled;errors=list(write_errors)
        elif switch=='native-session':enabled=settings.native_monitor_enabled;errors=list(write_errors)
        elif switch in ('native-notice','native-kick','native-ban-kick'):
            action='native-kick' if switch=='native-ban-kick' else switch
            enabled=settings.native_monitor_enabled and action in settings.native_control_actions
            if switch=='native-ban-kick':enabled=enabled and 'ban' in settings.writes
            errors=list(write_errors)
            if settings.write_approvals.get(action) is not True or (switch=='native-ban-kick' and settings.write_approvals.get('ban') is not True):errors.append('activation_missing')
        elif switch:
            enabled=switch in settings.writes;errors=list(write_errors)
            if settings.write_approvals.get(switch) is not True:errors.append('activation_missing')
            if switch=='maintenance':
                from .maintenance_requests import MaintenanceRequests
                if not MaintenanceRequests(db,settings).status()['execute_supported']:errors.append('maintenance_executor_missing')
            if switch=='batch-reward' and not settings.batch_worker_enabled:errors.append('worker_disabled')
            if switch in ('mail','reward','batch-reward') and catalog_state!='matched':errors.append('catalog_mismatch' if catalog_state=='mismatch' else 'catalog_unknown')
        else:errors=list(schema_errors)
        if implemented and not enabled:errors.insert(0,'disabled')
        state='not_implemented' if not implemented else 'disabled' if not enabled else 'attention' if errors else 'configured'
        validation=recorded['records'].get(key,{'state':'not_recorded'})
        rows.append({'id':key,'label':label,'group':group,'destination':destination,'implemented':implemented,
                     'enabled':bool(enabled),'state':state,'checks':[{'code':e,'message':REASONS[e]} for e in dict.fromkeys(errors)],
                     'verification':validation,'note':note})
    return {'checked_at':now,'application':release,'schema':{'state':schema_state,'versions':versions,'required':sorted(REQUIRED_SCHEMA)},
            'binding':binding,'catalog':{'state':catalog_state,'pvf_sha256':catalog_sha},'assets':{'state':asset_state},
            'runtime':{'fresh':live.get('fresh') is True,'collected_at':live.get('collected_at') if type(live.get('collected_at')) in (int,float) else None},
            'scope':{'test_only':bool(settings.test_uids),'test_account_count':len(settings.test_uids)},
            'evidence_state':recorded['state'],'items':rows,
            'note':'配置启用、当前前提检查和人工验收记录分开显示。本页不授予执行权限；实际目标、事务、原生协议和维护窗口必须在各操作入口重新校验。'}
