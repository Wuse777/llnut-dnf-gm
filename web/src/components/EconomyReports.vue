<script setup lang="ts">
import {ref,computed,onMounted,onBeforeUnmount,watch} from 'vue'
import {api,ApiError,uncertainMessage} from '../api'
const emit=defineEmits(['expired','inspect','player','support'])
const labels:Record<string,string>={cera:'点券',cera_point:'代币券',mileage:'积分',gold:'邮件金币',item:'道具件数'}
const sources:Record<string,string>={manual:'手动',batch:'批量任务',schedule:'定时任务'}
const receiptNames:Record<string,string>={unclaimed_marker:'未领取标记',claimed_marker:'已领取标记',deleted_marker:'删除标记',record_missing:'游戏记录缺失（未知）'}
const views=[['daily','每日趋势'],['items','物品排行'],['targets','接收账号'],['templates','礼包版本'],['reasons','操作原因'],['operations','操作明细'],['backlog','邮件积压'],['compensation','补偿核对']]
function beijingDay(offset=0){return new Date(Date.now()+8*3600000+offset*86400000).toISOString().slice(0,10)}
const start=ref(beijingDay(-6)),end=ref(beijingDay()),uid=ref(''),data=ref<any>(null),error=ref(''),fieldErrors=ref<Record<string,string>>({}),busy=ref(false),view=ref('daily'),metric=ref('cera')
const applied=ref<any>(null),ledger=ref<any>(null),backlog=ref<any>(null),compensation=ref<any>(null),sectionError=ref(''),sectionBusy=ref(false)
const before=ref(0),upper=ref(0),history=ref<number[]>([]),large=ref(false),coinThreshold=ref('100000'),goldThreshold=ref('100000000'),thresholdError=ref('')
const ledgerFilters=ref({large:false,currency_threshold:100000,gold_threshold:100000000})
const locked=computed(()=>busy.value||sectionBusy.value)
const changed=computed(()=>applied.value&&(start.value!==applied.value.start||end.value!==applied.value.end||Number(uid.value||0)!==applied.value.uid))
const totalMap=computed(()=>Object.fromEntries((data.value?.totals??[]).map((r:any)=>[r.metric,r])))
const daily=computed(()=>(data.value?.daily??[]).filter((r:any)=>r.metric===metric.value))
const queryString=computed(()=>applied.value?new URLSearchParams(Object.entries(applied.value).map(([k,v])=>[k,String(v)])).toString():'')
let alive=true,generation=0
function amount(v:unknown){try{return BigInt(String(v??0)).toLocaleString('zh-CN')}catch{return '未知'}}
function when(v:string){const d=new Date(v.endsWith('Z')?v:v+'Z');return Number.isNaN(+d)?'时间未知':d.toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false})}
function fail(e:unknown,section=false){if(section)sectionError.value=uncertainMessage(e);else error.value=uncertainMessage(e);if(e instanceof ApiError&&e.status===401)emit('expired')}
function validate(){
 fieldErrors.value={};const a=Date.parse(start.value+'T00:00:00Z'),b=Date.parse(end.value+'T00:00:00Z')
 if(!/^\d{4}-\d{2}-\d{2}$/.test(start.value)||!/^\d{4}-\d{2}-\d{2}$/.test(end.value)||!Number.isFinite(a)||!Number.isFinite(b)||b<a||b-a>=31*86400000)fieldErrors.value.range='请选择顺序正确、最多31天的日期范围（北京时间）'
 if(uid.value&&!/^[1-9]\d*$/.test(uid.value)||Number(uid.value)>2147483647)fieldErrors.value.uid='账号 UID 须为正整数，留空查看全部'
 return !Object.keys(fieldErrors.value).length
}
watch([start,end],()=>{delete fieldErrors.value.range})
watch(uid,()=>{delete fieldErrors.value.uid})
watch([coinThreshold,goldThreshold,large],()=>{thresholdError.value=''})
async function load(){
 if(locked.value||!validate())return
 const n=++generation;busy.value=true;error.value='';sectionError.value='';data.value=null;ledger.value=null;backlog.value=null;compensation.value=null;history.value=[];before.value=0;upper.value=0
 applied.value={start:start.value,end:end.value,uid:Number(uid.value||0)}
 try{const r=await api('/economy/summary?'+queryString.value);if(alive&&n===generation)data.value=r}catch(e){if(alive&&n===generation)fail(e)}finally{if(alive&&n===generation)busy.value=false}
 if(alive&&n===generation&&data.value)await loadSection()
}
async function loadSection(){
 if(locked.value||!data.value||!['operations','backlog','compensation'].includes(view.value))return
 const n=generation,target=view.value;sectionBusy.value=true;sectionError.value=''
 try{
  const extra=target==='operations'?'&'+new URLSearchParams({before:String(before.value),upper:String(upper.value),large:String(ledgerFilters.value.large),currency_threshold:String(ledgerFilters.value.currency_threshold),gold_threshold:String(ledgerFilters.value.gold_threshold)}):''
  const r=await api('/economy/'+target+'?'+queryString.value+extra)
  if(!alive||n!==generation||view.value!==target)return
  if(target==='operations'){ledger.value=r;upper.value=r.upper}else if(target==='backlog')backlog.value=r;else compensation.value=r
 }catch(e){if(alive&&n===generation){if(target==='operations')ledger.value=null;else if(target==='backlog')backlog.value=null;else compensation.value=null;fail(e,true)}}finally{if(alive&&n===generation)sectionBusy.value=false}
}
async function switchView(v:string){if(locked.value)return;view.value=v;sectionError.value='';if(v==='operations'&&!ledger.value||v==='backlog'&&!backlog.value||v==='compensation'&&!compensation.value)await loadSection()}
function preset(days:number){if(locked.value)return;start.value=beijingDay(1-days);end.value=beijingDay();void load()}
async function refreshLedger(){
 if(locked.value)return;thresholdError.value=''
 const coin=large.value?Number(coinThreshold.value):ledgerFilters.value.currency_threshold,gold=large.value?Number(goldThreshold.value):ledgerFilters.value.gold_threshold
 if(large.value&&(!/^\d+$/.test(coinThreshold.value)||!Number.isSafeInteger(coin)||coin<1||coin>4294967295||!/^\d+$/.test(goldThreshold.value)||!Number.isSafeInteger(gold)||gold<1||gold>1000000000)){thresholdError.value='请输入正整数阈值：账号货币不超过4,294,967,295，邮件金币不超过10亿；阈值仅筛选，不限制发放';return}
 ledgerFilters.value={large:large.value,currency_threshold:coin,gold_threshold:gold};before.value=0;upper.value=0;history.value=[];await loadSection()
}
async function next(){if(!ledger.value?.next_before||locked.value)return;history.value.push(before.value);before.value=ledger.value.next_before;await loadSection()}
async function previous(){if(!history.value.length||locked.value)return;before.value=history.value.pop()!;await loadSection()}
onMounted(load);onBeforeUnmount(()=>{alive=false;generation++})
</script>
<template><section class="economy-reports">
 <header><h2>GM 发放统计与核对</h2><p class="muted">只读报表，不修改游戏数据。金额按原始整数展示，不用四舍五入的“万／亿”替代精确值。</p></header>
 <form class="report-filters panel" @submit.prevent="load">
  <label>开始日期（北京时间）<input v-model="start" type="date" aria-label="统计开始日期" :disabled="locked"></label><label>结束日期（包含当日）<input v-model="end" type="date" aria-label="统计结束日期" :disabled="locked"></label>
  <label>账号 UID<input v-model="uid" inputmode="numeric" aria-label="统计账号 UID" placeholder="留空查看全部" :disabled="locked"><small v-if="fieldErrors.uid" class="field-error" role="alert">{{fieldErrors.uid}}</small></label><button class="primary" :disabled="locked">查询统计</button>
  <small v-if="fieldErrors.range" class="field-error wide" role="alert">{{fieldErrors.range}}</small><div class="button-row wide"><button type="button" :disabled="locked" @click="preset(1)">今天</button><button type="button" :disabled="locked" @click="preset(7)">近7天</button><button type="button" :disabled="locked" @click="preset(30)">近30天</button></div>
  <p v-if="error" class="submit-error wide" role="alert">{{error}}</p>
 </form>
 <p v-if="busy" role="status">正在读取统计，请稍候…</p>
 <template v-if="data">
 <p class="notice">{{data.note}}</p><p class="muted">当前结果：{{applied.start}} 至 {{applied.end}} · 北京时间 · {{applied.uid?'UID '+applied.uid:'全部GM目标'}} · 采集于 {{new Date(data.generated_at*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})}}</p>
 <p v-if="changed" class="warning" role="status">筛选表单已改变，下面仍是上一次查询的结果；请点击“查询统计”。导出也使用上一次查询范围。</p>
 <section class="panel coverage" :class="{warning:data.coverage.state!=='complete'}"><h3>统计覆盖情况</h3><p>成功奖励审计 {{data.coverage.reward_audits}} 笔；已解析 {{data.coverage.complete}} 笔；历史内容不完整 {{data.coverage.incomplete}} 笔；尚未导入 {{data.coverage.unprojected}} 笔。</p><p v-if="data.coverage.state!=='complete'" role="alert">以下金额仅为已解析记录的小计，不是所选范围完整总计。请维护人员导入历史并核对不完整记录，不要按0补齐。</p><small>空时间范围没有记录，不代表全服没有经济活动。</small></section>
 <div class="metric-cards"><article v-for="(name,id) in labels" :key="id" class="panel"><h3>{{name}}</h3><p>发放 <b>{{amount(totalMap[id]?.issued)}}</b></p><p>扣减 <b>{{amount(totalMap[id]?.deducted)}}</b></p><p>净变更 <b>{{amount(totalMap[id]?.net)}}</b></p></article></div>
 <div class="report-tabs" role="group" aria-label="统计视图"><button v-for="[id,name] in views" :key="id" :aria-pressed="view===id" :disabled="locked" @click="switchView(id)">{{name}}</button></div>
 <section class="panel report-body">
 <template v-if="view==='daily'"><div class="section-title"><h3>按日统计</h3><label>统计指标<select v-model="metric" aria-label="每日统计指标"><option v-for="(name,id) in labels" :key="id" :value="id">{{name}}</option></select></label></div><p v-if="!daily.length" class="empty">该指标没有已解析记录。</p><div v-else class="table-wrap"><table><thead><tr><th>日期</th><th>发放</th><th>扣减</th><th>净变更</th></tr></thead><tbody><tr v-for="r in daily" :key="r.day"><td>{{r.day}}</td><td>{{amount(r.issued)}}</td><td>{{amount(r.deducted)}}</td><td>{{amount(r.net)}}</td></tr></tbody></table></div></template>
 <template v-if="view==='items'"><h3>物品发放前50项</h3><p class="muted">不同PVF版本分开统计；名称来自当次奖励快照，不拿当前索引冒充历史。</p><p v-if="!data.items.length" class="empty">没有已解析的物品发放。</p><article v-for="r in data.items" :key="r.item_id+r.pvf_sha256" class="report-row"><b>{{r.item_name}} #{{r.item_id}}</b><span>{{amount(r.quantity)}} 件 · {{r.operations}} 笔</span><code>PVF {{r.pvf_sha256}}</code></article></template>
 <template v-if="view==='targets'"><h3>接收账号前20名（按操作笔数）</h3><p v-if="!data.targets.length" class="empty">没有已解析的目标。</p><article v-for="r in data.targets" :key="r.target_uid" class="report-row"><b>UID {{r.target_uid}}</b><span>{{r.operations}} 笔</span><button :disabled="!r.target_uid" @click="emit('player',r.target_uid)">查看此玩家</button></article></template>
 <template v-if="view==='templates'"><h3>使用最多的礼包版本（前20项）</h3><p v-if="!data.templates.length" class="empty">没有带礼包来源的已解析操作。</p><article v-for="r in data.templates" :key="r.template_id+':'+r.template_version" class="report-row"><b>礼包 #{{r.template_id}} · v{{r.template_version??'未知'}}</b><span>{{r.operations}} 笔奖励操作（不是附件数量）</span></article></template>
 <template v-if="view==='reasons'"><h3>操作原因（前20项）</h3><p v-if="!data.reasons.length" class="empty">没有已解析记录。</p><article v-for="r in data.reasons" :key="r.reason" class="report-row"><b>{{r.reason}}</b><span>{{r.operations}} 笔</span></article><h4>操作来源</h4><p v-for="r in data.sources" :key="r.source">{{sources[r.source]||'未知来源'}}：{{r.operations}} 笔</p></template>
 <template v-if="view==='operations'"><h3>操作明细与大额筛选</h3><form class="report-filters" @submit.prevent="refreshLedger"><label class="check"><input v-model="large" type="checkbox" aria-label="只看大额操作" :disabled="locked">只看大额操作</label><label>账号货币绝对值阈值<input v-model="coinThreshold" inputmode="numeric" aria-label="货币筛选阈值" :disabled="locked||!large"></label><label>邮件金币阈值<input v-model="goldThreshold" inputmode="numeric" aria-label="金币筛选阈值" :disabled="locked||!large"></label><button :disabled="locked">刷新操作明细</button><p v-if="thresholdError" class="field-error wide" role="alert">{{thresholdError}}</p></form><p class="muted">阈值只用于筛选线索，不限制充值或发放。导出为该日期/账号下全部已投影明细，不继承“大额”筛选；必须检查文件末尾 complete 标记。</p><a :href="'/dnf-gm/api/v1/economy/export?'+queryString" download>导出明细（NDJSON）</a>
 <template v-if="ledger"><p class="muted">当前明细筛选：{{ledgerFilters.large?'大额操作（货币绝对值 ≥ '+amount(ledgerFilters.currency_threshold)+' 或金币 ≥ '+amount(ledgerFilters.gold_threshold)+'）':'全部操作'}}。</p><p v-if="!ledger.items.length" class="empty">没有符合条件的记录。</p><article v-for="r in ledger.items" :key="r.operation_id" class="report-row"><div class="section-title"><b>UID {{r.target_uid}}<span v-if="r.charac_no"> · 角色 #{{r.charac_no}}</span></b><small>{{when(r.created_at)}} · {{sources[r.source]}}</small></div><p>{{r.reason}}</p><p v-if="!r.complete" class="warning">{{r.issue}}</p><p v-for="v in r.values" :key="v.metric+':'+v.item_id+v.pvf_sha256">{{v.metric==='item'?(v.item_name+' #'+v.item_id):labels[v.metric]}}：{{amount(v.amount)}}</p><code>{{r.operation_id}}</code><div class="button-row"><button @click="emit('inspect',r.operation_id)">查看原操作</button><button :disabled="!r.target_uid" @click="emit('player',r.target_uid)">查看此玩家</button></div></article><div class="pagination"><button :disabled="locked||!history.length" @click="previous">上一页明细</button><span>第 {{history.length+1}} 页</span><button :disabled="locked||!ledger.next_before" @click="next">下一页明细</button></div></template></template>
 <template v-if="view==='backlog'"><div class="section-title"><h3>所选投递日期的邮件积压</h3><button :disabled="locked" @click="loadSection">刷新邮件标记</button></div><template v-if="backlog"><p class="notice">{{backlog.note}}</p><p>邮件批次 {{backlog.coverage.batches}}；历史不完整批次 {{backlog.coverage.incomplete_batches}}；未记录附件 {{amount(backlog.coverage.unrecorded)}} 条；已投影邮件操作中缺少投递台账 {{backlog.coverage.missing_mail_ledgers}} 笔。</p><article v-for="s in backlog.states" :key="s.receipt_state" class="report-row"><b>{{receiptNames[s.receipt_state]}}</b><span>{{s.records}} 条附件 · {{amount(s.gold)}} 金币 · {{amount(s.quantity)}} 件</span></article><h4>最早的未领取附件（最多20条）</h4><p v-if="!backlog.oldest.length" class="empty">当前范围没有可见的未领取标记，不推断缺失记录已领取。</p><article v-for="r in backlog.oldest" :key="r.postal_id" class="report-row"><b>{{r.character_name}} · UID {{r.target_uid}}</b><span>{{when(r.created_at)}} · 邮件附件 #{{r.postal_id}}</span><p>物品 #{{r.item_id}} × {{amount(r.quantity)}} · {{amount(r.gold)}} 金币</p><button @click="emit('inspect',r.operation_id)">查看原操作</button></article></template></template>
 <template v-if="view==='compensation'"><div class="section-title"><h3>多次补偿核对</h3><button :disabled="locked" @click="loadSection">刷新补偿线索</button></div><template v-if="compensation"><p class="notice">{{compensation.note}}</p><p v-if="compensation.has_more" class="warning">仅展示前20个问题，请缩短日期范围或按UID继续核对。</p><p v-if="!compensation.items.length" class="empty">已投影记录中未找到符合条件的问题；未导入记录不在此结果中。</p><article v-for="r in compensation.items" :key="r.case_id" class="report-row"><b>{{r.title}}</b><p>UID {{r.uid}} · 全历史补偿 {{r.compensation_count}} 笔 · 本期关联 {{r.matches_in_window}} 笔</p><code>{{r.case_id}}</code><button @click="emit('support',r.uid)">查看玩家问题</button></article></template></template>
 <p v-if="sectionBusy" role="status">正在读取所选明细…</p><p v-if="sectionError" class="submit-error" role="alert">{{sectionError}} <button :disabled="locked" @click="loadSection">重试当前视图</button></p>
 </section></template>
</section></template>
<style scoped>
.economy-reports{display:grid;gap:20px}.report-filters{display:flex;flex-wrap:wrap;gap:12px;align-items:end}.report-filters label{display:grid;gap:6px;flex:1 1 180px}.report-filters .wide{flex-basis:100%;margin:0}.report-filters .check{display:flex;align-items:center}.check input{width:auto}.metric-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}.metric-cards h3{margin:0 0 12px}.metric-cards p{display:flex;gap:8px;justify-content:space-between;flex-wrap:wrap}.report-tabs,.button-row{display:flex;flex-wrap:wrap;gap:8px}.report-tabs [aria-pressed=true]{background:var(--bg-primary);outline:1px solid var(--border-color)}.report-body{min-width:0}.report-row{display:grid;gap:8px;padding:16px 0;border-bottom:1px solid var(--border-color);min-width:0}.report-row p{margin:0}.report-row button{justify-self:start}.report-row code,.report-row b,.report-row p{overflow-wrap:anywhere}.report-row .section-title{flex-wrap:wrap}.report-body table{width:100%;font-variant-numeric:tabular-nums}.report-body td,.report-body th{white-space:normal;overflow-wrap:anywhere}.report-body .table-wrap{max-width:100%;overflow:auto}@media(max-width:600px){.report-tabs>button{flex:1 1 130px}.report-filters>button{width:100%}.metric-cards{grid-template-columns:1fr 1fr}.metric-cards article:last-child{grid-column:1/-1}.report-row .button-row button{flex:1}.report-body .section-title{align-items:start}}
</style>
