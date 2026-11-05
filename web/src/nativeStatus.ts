export const supportNames:Record<string,string>={'player-profile':'玩家备注与标签','case-create':'建立玩家问题','case-update':'更新玩家问题','case-comment':'追加问题处理记录','case-link':'关联问题操作'}
export const inventoryNames:Record<string,string>={'char-rescue':'卡死位置救援','char-rename':'角色改名','char-fatigue':'角色疲劳调整','item-edit':'装备属性修改','item-reclaim':'存档物品回收','item-restore':'存档快照恢复','item-intent':'装备执行意向','item-aborted':'装备中断核对','item-cancel':'取消装备预览'}
export const inventoryStates:Record<string,string>={preview:'待确认预览',executing:'执行意向已记录，结果待核对',committed:'数据库已提交（游戏效果待核验）',cancelled:'预览已取消',aborted:'确认未提交游戏事务'}
export const nativeNames:Record<string,string>={'native-notice':'全服公告','native-kick':'账号踢下线','native-ban-kick':'封禁并尝试踢下线'}
export const nativeStates:Record<string,string>={preview:'仅预览，尚未发送',dispatching:'发送占位已提交，结果待确认',sent:'指令已发送，游戏效果未确认',not_sent:'指令未发送',uncertain:'发送结果不确定，禁止自动重发',cancelled:'预览已取消，未发送'}
export function operationStatus(row:any){
 if(row?.action?.startsWith('item-')||['char-fatigue','char-rename','char-rescue'].includes(row?.action))return inventoryStates[row.status]||'装备操作状态未知'
 if(row?.action?.startsWith('native-'))return nativeStates[row.status]||'原生控制状态未知'
 return row?.status==='queued'?'已审计入队，不代表执行完成':row?.status==='cancelled'?'预览已取消':row?.status==='committed'?'数据库已提交':'未提交 / 仅预览'
}

export const nativeReasons:Record<string,string>={dispatch_claimed:'防重记录已提交，尚无最终发送记录',no_application_ack:'指令已发送，原生服务没有提供业务回执',connection_failed:'连接原生服务失败，没有发送指令',send_uncertain:'发送时发生异常，无法确定是否到达',transport_exception:'处理异常，无法确定发送结果',readiness_changed_after_claim:'提交后服务或资源状态变化，未发送指令',cancelled:'管理员取消了未发送的预览',busy:'原生接口正在处理其他请求，未发送指令',disabled:'该控制能力已停用，未发送指令',stale_snapshot:'采集快照已过期，未发送指令',core_unhealthy:'核心服务状态异常，未发送指令',protocol_unverified:'原生程序指纹校验失败，未发送指令',image_mismatch:'游戏镜像指纹不匹配，未发送指令',broadcast_test_scope:'测试范围内不允许广播，未发送指令',test_target_only:'目标不在测试账号范围，未发送指令'}
