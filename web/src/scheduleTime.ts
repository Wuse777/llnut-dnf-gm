/** Inputs always mean Asia/Shanghai, regardless of the browser's local zone. */
export function shanghaiInput(timestamp:number):string {
 return new Date((timestamp+8*3600)*1000).toISOString().slice(0,16)
}
export function shanghaiTimestamp(input:string):number {
 if(!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(input))throw new Error('请填写完整的北京时间')
 const timestamp=Date.parse(input+':00+08:00')/1000
 if(!Number.isFinite(timestamp)||shanghaiInput(timestamp)!==input)throw new Error('时间无效，请检查日期与时刻')
 return timestamp
}
export function scheduleTime(timestamp:number|null):string {
 return timestamp==null?'无后续期次':new Date(timestamp*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false})
}
export const scheduleStates:Record<string,string>={preview:'待确认',active:'已启用',paused:'已暂停',cancelled:'已取消',completed:'已结束',needs_attention:'需要处理',awaiting:'公告准备／结果待核对',running:'奖励任务执行中',finished:'奖励数据库已提交',sent:'公告已发送，效果未知',skipped:'错过，未补发'}
