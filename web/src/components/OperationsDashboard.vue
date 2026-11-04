<script setup lang="ts">
import {ref,onMounted,onBeforeUnmount} from 'vue'
import {api,uncertainMessage} from '../api'
import ReleaseCleanup from './ReleaseCleanup.vue'
import AlertHealth from './AlertHealth.vue'
import BackupHealth from './BackupHealth.vue'
import TaskHealth from './TaskHealth.vue'
const emit=defineEmits<{reauth:[],task:[kind:string,id:string]}>()
const data=ref<any>(null),windowSize=ref('24h'),before=ref(0),pages=ref<number[]>([]),busy=ref(false),error=ref('')
let timer:ReturnType<typeof setInterval>|undefined,alive=true,generation=0
const labels:Record<string,string>={cpu_percent:'CPU峰值',mem_available_mib:'可用物理内存最低值',swap_free_mib:'Swap剩余最低值',disk_free_gib:'磁盘可用最低值'}
const units:Record<string,string>={cpu_percent:'%',mem_available_mib:'MiB',swap_free_mib:'MiB',disk_free_gib:'GiB'}
const events:Record<string,string>={probe_timeout:'固定探测超时',probe_slow:'固定探测耗时偏长',protection_stop:'保护停止GM',auto_recovery:'采集故障后恢复GM',auto_recovery_cancelled:'自动恢复已取消',collection_failed:'采集失败',collection_recovered:'采集恢复',monitor_failed:'监控程序异常'}
const reasons:Record<string,string>={resource_failure:'连续资源不足',core_failure:'连续核心检查失败',collector_failed:'采集持续失败',auto_recovery_cancelled:'自动恢复取消'}
const fieldNames:Record<string,string>={reason:'原因',probe:'检查项',error_type:'错误类型',timeout_seconds:'超时秒数',elapsed_seconds:'耗时秒数',auto_recovery_pending:'等待自动恢复',success:'成功',core_ok:'核心检查通过',cpu_percent:'CPU%',mem_available_mib:'可用内存MiB',mem_total_mib:'总内存MiB',swap_free_mib:'Swap剩余MiB',swap_total_mib:'Swap总量MiB',disk_free_gib:'可用磁盘GiB',disk_total_gib:'磁盘总量GiB'}
const states:Record<string,string>={ok:'已采集',missing:'目录不存在',unavailable:'不可读取',unknown:'未知',timeout:'扫描超时',symlink_refused:'拒绝跟随符号链接'}
function timestamp(value:any){return typeof value==='number'?new Date(value*1000).toLocaleString('zh-CN',{hour12:false}):'未记录'}
function number(value:any){return typeof value==='number'&&Number.isFinite(value)?value.toLocaleString('zh-CN',{maximumFractionDigits:2}):'未知'}
function bytes(value:any){return typeof value==='number'?number(value/2**30)+' GiB':'未知'}
async function load(reset=false){if(busy.value)return;if(reset){before.value=0;pages.value=[]}busy.value=true;error.value='';const ticket=++generation
 try{const d=await api('/operations-dashboard?window='+windowSize.value+'&before='+before.value);if(alive&&ticket===generation)data.value=d}
 catch(e){if(alive&&ticket===generation){data.value=null;error.value=uncertainMessage(e)}}finally{if(alive&&ticket===generation)busy.value=false}}
function next(){if(data.value?.next_before==null)return;pages.value.push(before.value);before.value=data.value.next_before;void load()}
function previous(){before.value=pages.value.pop()??0;void load()}
function paths(key:string){
 const points=data.value?.points??[],bucket=data.value?.bucket_seconds??300
 const values=points.map((p:any)=>p[key]).filter((v:any)=>typeof v==='number'&&Number.isFinite(v));if(!values.length)return []
 const max=key==='cpu_percent'?100:Math.max(...values,1),end=data.value?.as_of??Date.now()/1000,start=end-(windowSize.value==='24h'?86400:604800)
 const paths:string[]=[];let path='',last:number|undefined
 for(const p of points){const time=p.minute*60,v=p[key];if(typeof v!=='number'||!Number.isFinite(v)){if(path)paths.push(path);path='';last=undefined;continue}
  if(last!==undefined&&time-last>bucket*1.5){if(path)paths.push(path);path=''}
  const x=Math.max(0,Math.min(600,(time-start)/(end-start)*600)),y=92-Math.min(1,v/max)*80
  path+=(path?' L':'M')+x.toFixed(1)+','+y.toFixed(1);last=time
 }
 if(path)paths.push(path);return paths.map(p=>p.includes(' L')?p:p+' l0.01,0')
}
function axisStart(){return timestamp((data.value?.as_of??Date.now()/1000)-(windowSize.value==='24h'?86400:604800))}
function storageRows(){return [...(data.value?.storage?.items??[])].sort((a,b)=>(b.bytes??-1)-(a.bytes??-1))}
function healthMinutes(key:string){return (data.value?.points??[]).reduce((n:number,p:any)=>n+(p[key]??0),0)}
function range(key:string){const v=(data.value?.points??[]).map((p:any)=>p[key]).filter((v:any)=>typeof v==='number'&&Number.isFinite(v));return v.length?`${number(Math.min(...v))} — ${number(Math.max(...v))} ${units[key]}`:'无可用观测'}
onMounted(()=>{void load();timer=setInterval(()=>{if(!document.hidden&&before.value===0)void load()},30000)})
onBeforeUnmount(()=>{alive=false;generation++;if(timer)clearInterval(timer)})
</script>
<template><div class="ops-dashboard">
 <section class="panel"><div class="section-title"><h2>运行诊断</h2><div class="button-row"><select v-model="windowSize" aria-label="资源历史窗口" :disabled="busy" @change="load(true)"><option value="24h">最近24小时</option><option value="7d">最近7天</option></select><button :disabled="busy" @click="load()">刷新诊断</button></div></div><p class="field-hint">仅诊断GM与服务器状态，不提供任意命令或核心服务重启。默认30秒刷新，隐藏页面暂停；历史样本不倒填。</p><p v-if="busy" role="status">正在读取诊断…</p><p v-if="error" class="submit-error" role="alert">{{error}}</p>
 <template v-if="data"><p :class="data.fresh?'field-hint':'warning'">{{data.message}} · 最后采集 {{timestamp(data.updated_at)}}</p><div class="metrics ops-current"><article v-for="(label,key) in labels" :key="key"><span>{{label.replace('峰值','使用率').replace('最低值','')}}</span><strong>{{number(data.current?.fresh?data.current[key]:null)}}</strong><small>{{units[key]}} · {{data.current?.fresh?'实时采集':'当前快照过期/未知'}}</small></article></div><p class="field-hint">监控健康门槛：{{data.current?.core_ok===true?'本次通过':data.current?.core_ok===false?'本次未通过':'未知'}}；快照 {{timestamp(data.current?.collected_at)}}。故障后GM可能停止，停止期间网页也可能无法打开；恢复后可回看持久记录。</p></template>
 </section>
 <AlertHealth/>
 <BackupHealth/>
 <TaskHealth @inspect="(kind,id)=>emit('task',kind,id)"/>
 <template v-if="data">
 <section class="panel"><div class="section-title"><h2>资源趋势</h2><span class="pill">{{data.coverage_samples??0}} / {{data.expected_samples??(windowSize==='24h'?1440:10080)}}分钟有记录</span></div><p class="field-hint">{{windowSize==='24h'?'5':'30'}}分钟聚合：CPU取峰值，内存/Swap/磁盘取最低可用量。缺口断开，不用零值或旧数据补齐；各图纵轴从0开始、独立缩放（CPU固定0–100%）。</p><p class="field-hint">有监控未就绪观测 {{healthMinutes('failed_samples')}} 分钟 · 采集状态未知 {{healthMinutes('unknown_samples')}} 分钟；不含完全未采样的时间。</p><div class="ops-trends"><article v-for="(label,key) in labels" :key="key"><h3>{{label}}</h3><p>{{range(key)}}</p><svg v-if="paths(key).length" viewBox="0 0 600 104" role="img" :aria-label="label+'趋势，'+range(key)"><line x1="0" y1="92" x2="600" y2="92"/><path v-for="(d,i) in paths(key)" :key="i" :d="d"/></svg><p v-else class="empty">还没有这一指标的历史数据</p><div class="ops-axis"><span>{{axisStart()}}</span><span>现在</span></div></article></div></section>
 <section class="panel"><h2>保护停机与恢复</h2><template v-if="data.protection"><p class="warning">最近记录：{{reasons[data.protection.reason]||data.protection.reason||'原因未知'}} · {{timestamp(data.protection.stopped_at)}}</p><p>自动恢复等待：{{data.protection.auto_recovery_pending===true?'是':'否/未记录'}} · 人工恢复标记：{{data.protection.manual_restart_required===true?'需要人工检查':'无此标记'}}</p><p>恢复时间：{{timestamp(data.protection.recovered_at)}} · 结果：{{data.protection.recovery_result==='started'?'曾发出成功启动请求（不是当前健康保证）':data.protection.recovery_result==='failed'?'启动失败':'未记录'}}</p></template><p v-else class="empty">没有可读取的保护记录，不代表从未发生故障。</p>
 <div v-if="data.events.length" class="table-wrap"><table class="ops-detail-table"><thead><tr><th>时间</th><th>事件</th><th>脱敏详情</th></tr></thead><tbody><tr v-for="e in data.events" :key="e.id"><td data-label="时间">{{timestamp(e.occurred_at)}}</td><td data-label="事件">{{events[e.name]||e.name}}</td><td data-label="详情"><span v-for="(value,key) in e.details" :key="key" class="ops-event-field">{{fieldNames[key]||key}}: {{typeof value==='boolean'?(value?'是':'否'):(reasons[String(value)]||String(value))}}</span></td></tr></tbody></table></div><p v-else class="empty">本页没有事件。</p><div class="pagination"><button :disabled="busy||!pages.length" @click="previous">较新事件</button><span>第{{pages.length+1}}页 · 保留最近256条</span><button :disabled="busy||data.next_before==null" @click="next">较早事件</button></div></section>
 <section class="panel"><h2>存储占用分类</h2><p class="field-hint">固定目录每小时后台扫描，单目录5秒超时；不是实时计费容量。无法扫描时显示未知，不按0计算。</p><template v-if="data.storage"><p :class="Date.now()/1000-data.storage.collected_at>7200?'warning':'field-hint'">采集 {{timestamp(data.storage.collected_at)}}{{Date.now()/1000-data.storage.collected_at>7200?' · 已过期，仅供参考':''}}</p><div class="table-wrap"><table class="ops-detail-table"><thead><tr><th>类别</th><th>占用</th><th>状态</th><th>采集时间</th></tr></thead><tbody><tr v-for="s in storageRows()" :key="s.id"><td data-label="类别">{{s.label}}</td><td data-label="占用">{{s.state==='ok'?bytes(s.bytes):'未知'}}</td><td data-label="状态">{{states[s.state]||'未知'}}</td><td data-label="采集">{{timestamp(s.collected_at)}}</td></tr></tbody></table></div><p class="warning">{{data.storage.note}}</p></template><p v-else class="empty">尚未配置固定扫描目录或首轮扫描未完成。</p></section>
 <section class="panel"><h2>运行版本与保留发布包</h2><p>应用版本 {{data.application.version}} · 管理库版本：{{data.application.schema_state==='ok'?data.application.schema_versions.map((v:any)=>v.version).join(' / '):'查询失败'}}</p><p class="field-hint">下面只读列出GM发布目录，不提供删除游戏数据、日志或备份的入口。需要清理时使用下方签名清单，不能直接按此只读列表删除。</p><template v-if="data.releases"><p v-if="data.releases.truncated" class="warning">目录条目超过扫描上限，列表不完整。</p><div class="table-wrap"><table class="ops-detail-table"><thead><tr><th>发布目录</th><th>源码版本</th><th>目录修改时间（非部署时间）</th><th>保留保护</th></tr></thead><tbody><tr v-for="r in data.releases.items" :key="r.name"><td data-label="目录" class="mono">{{r.name}}</td><td data-label="源码" class="mono">{{r.source_revision||'未知'}}</td><td data-label="目录时间">{{timestamp(r.modified_at)}}</td><td data-label="保护">{{r.protected?'当前/回滚版本，禁止清理':'历史目录，仅供盘点'}}</td></tr></tbody></table></div><p class="field-hint">{{data.releases.note}}</p></template><p v-else class="empty">暂无发布目录盘点。</p></section>
 </template>
<ReleaseCleanup @reauth="emit('reauth')"/>
</div></template>
