"""Sanitized evidence for the reviewed server plugin, never a script executor.

A disk fingerprint proves which source was observed, NOT which hook is loaded.
No plugin text, connection configuration, paths, addresses or credentials are
returned. Unknown/stale evidence cannot inherit a previously matched report.
"""
from pathlib import Path
import hashlib
import os
import stat

REVIEWED_SCRIPT_SHA256='3abc5f460fb8f2803a6266c31373fe0d5bb4f2fe94f0c3d3263eece97dce3926'
MAX_SCRIPT_BYTES=256*1024


def source_fingerprint(path):
    """Root collector only: bounded regular file, no symlink and no evaluation."""
    fd=None
    try:
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or not 0<before.st_size<=MAX_SCRIPT_BYTES:
            raise ValueError('Unsupported plugin source')
        signature=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
        with os.fdopen(fd,'rb') as stream:
            fd=None;body=stream.read(MAX_SCRIPT_BYTES+1);after=os.fstat(stream.fileno())
        if len(body)!=before.st_size or signature(before)!=signature(after) or signature(before)!=signature(Path(path).lstat()):
            raise ValueError('Plugin source changed')
        return {'schema':1,'source_state':'observed','source_sha256':hashlib.sha256(body).hexdigest()}
    except (OSError,ValueError):
        return {'schema':1,'source_state':'unavailable','source_sha256':None}
    finally:
        if fd is not None:os.close(fd)


STARTUP=[
    {'id':'tower','label':'绝望之塔修复','source_setting':'启动时调用，参数为 true','scope':'加载此脚本的游戏进程','activation':'游戏组件下次加载脚本时；不提供热更新'},
    {'id':'emblem','label':'徽章镶嵌修复','source_setting':'启动时注册','scope':'加载此脚本的游戏进程','activation':'游戏组件下次加载脚本时；不提供热更新'},
    {'id':'avatar','label':'装扮潜能','source_setting':'启动时注册','scope':'加载此脚本的游戏进程','activation':'游戏组件下次加载脚本时；不提供热更新'},
    {'id':'village','label':'怪物攻城及上下线处理','source_setting':'启动时注册处理与活动调度','scope':'对应游戏进程／频道','activation':'脚本加载及活动调度；并非账号权限开关'},
    {'id':'return','label':'勇士归来判定时间','source_setting':'启动时传入 15 天','scope':'加载此脚本的游戏进程','activation':'游戏组件下次加载脚本时；当前内存值未核验'},
    {'id':'online-reward','label':'在线奖励','source_setting':'主启动函数中的调用被注释','scope':'仅说明该启动入口未调用','activation':'不排除其他入口／组件，不能据此宣称全服关闭'},
]


def report(settings):
    from .catalog import snapshot
    live=snapshot(settings);evidence=live.get('plugin_source')
    fresh=live.get('fresh') is True
    sha=evidence.get('source_sha256') if fresh and isinstance(evidence,dict) and evidence.get('schema')==1 else None
    observed=(isinstance(evidence,dict) and evidence.get('source_state')=='observed' and
              isinstance(sha,str) and len(sha)==64 and all(c in '0123456789abcdef' for c in sha))
    state='matched' if observed and sha==REVIEWED_SCRIPT_SHA256 else 'unreviewed' if observed else 'unknown'
    return {'state':state,'collected_at':live.get('collected_at'),'fresh':fresh,
        'source_sha256':sha if observed else None,'runtime_state':'not_verified','editable':False,
        'startup':STARTUP if state=='matched' else [],
        'configuration':{'state':'database_connection_only' if state=='matched' else 'unknown',
            'editable_gameplay_keys':[],
            'note':'已核对脚本只从JSON读取数据库连接配置，没有确认可编辑的游戏效果开关；连接凭据不在网页读取、展示或修改。' if state=='matched' else '当前脚本尚无新鲜匹配证据，不套用旧版本的配置说明。'},
        'client':{'state':'not_inspected','features':['技能0CD','无敌等客户端辅助'],
            'note':'客户端菜单不等于服务端账号权限。当前服务端脚本证据无法证明这些功能的来源、默认状态、账号范围或能否被服务器禁止。普通账号、GM账号均不能据此推断。'},
        'note':'以下是磁盘脚本的已核对启动配置，不是运行中插件状态。网页不新增注入、不执行脚本、不自动重启游戏，不把GM功能权限开关当作客户端插件控制。'}
