<script setup lang="ts">
import {ref,computed,onMounted,onBeforeUnmount} from 'vue'
import {api,ApiError,uncertainMessage} from '../api'
import RewardJobs from './RewardJobs.vue'
import {shanghaiInput,shanghaiTimestamp,scheduleTime,scheduleStates} from '../scheduleTime'
const emit=defineEmits<{reauth:[],expired:[],child:[kind:string,id:string]}>()
const title=ref(''),kind=ref('reward'),first=ref(shanghaiInput(Math.floor(Date.now()/1000)+3600)),recurrence=ref('once'),end=ref(''),message=ref(''),reason=ref('')
const showDraft=ref(true),seed=ref<any>(null),draftKey=ref(0),fields=ref<Record<string,string>>({}),error=ref(''),busy=ref(false),items=ref<any[]>([]),runs=ref<any[]>([]),selected=ref<any>(null),page=ref(1),runPage=ref(1)
const confirmation=ref(''),recurringAck=ref(false),repeatAck=ref(false),attentionAck=ref(false),canActivate=ref(false),uncertain=ref(false),activationKey=ref(''),query=ref(''),workerEnabled=ref(false)
const storage='dnfgm-schedule-id'
let alive=true,timer:ReturnType<typeof setInterval>|undefined
const labels=scheduleStates
const recurring=computed(()=>selected.value?.request.recurrence!=='once')
const fullScope=computed(()=>selected.value?.kind==='notice'?'全服公告':selected.value?.request.reward_job?.targets.mode==='all'?'全服发放':'')
const repeated=computed(()=>selected.value?.request.reward_job?.account_reward_mode==='per_character'&&Object.values(selected.value?.request.reward_job?.reward.currency_rewards||{}).some(Boolean))
function fail(e:unknown){error.value=uncertainMessage(e);if(e instanceof ApiError&&e.status===403&&e.message.includes('认证'))emit('reauth');if(e instanceof ApiError&&e.status===401)emit('expired')}
function remember(id:string){try{sessionStorage.setItem(storage,id)}catch{}}
async function list(){const r=await api('/schedules?page='+page.value);if(alive){items.value=r.items;workerEnabled.value=r.worker_enabled}}
async function read(id:string){
 if(!/^[a-f0-9]{32}$/.test(id))throw new Error('请输入32位计划编号')
 const [r,h]=await Promise.all([api('/schedules/'+id),api(`/schedules/${id}/runs?page=${runPage.value}`)])
 if(!alive)return
 selected.value=r;showDraft.value=false;runs.value=h.items;query.value=id;remember(id)
 if(r.status!=='preview'){uncertain.value=false;canActivate.value=false}
}
async function inspect(id=query.value){if(busy.value)return;busy.value=true;error.value='';if(id!==selected.value?.id){canActivate.value=false;runPage.value=1}try{await read(id);await list()}catch(e){fail(e)}finally{busy.value=false}}
async function preview(rewardJob?:any){
 if(busy.value||uncertain.value)return
 error.value='';fields.value={};let due=0,until:number|null=null
 if(!title.value.trim())fields.value.title='请填写计划名称'
 try{due=shanghaiTimestamp(first.value);if(due<=Date.now()/1000)throw new Error('首次执行时间必须在未来')}catch(e){fields.value.first=uncertainMessage(e)}
 if(recurrence.value!=='once'&&end.value){try{until=shanghaiTimestamp(end.value);if(until<due)throw new Error('结束时间不能早于首次执行时间')}catch(e){fields.value.end=uncertainMessage(e)}}
 if(kind.value==='notice'){
  if(!reason.value.trim())fields.value.reason='请填写公告原因'
  if(!message.value.trim())fields.value.message='请填写公告文字'
  else if(/\p{C}/u.test(message.value)||new TextEncoder().encode(message.value).length>254)fields.value.message='公告须为单行文字，最多254个UTF-8字节'
 }
 if(Object.keys(fields.value).length){error.value='请修正上方对应输入项旁的提示；没有创建计划。';return}
 busy.value=true
 try{
  const r=await api('/schedules/preview','POST',{title:title.value.trim(),kind:kind.value,first_due:due,recurrence:recurrence.value,end_at:until,reward_job:kind.value==='reward'?rewardJob:null,notice:kind.value==='notice'?{action:'native-notice',message:message.value,reason:reason.value.trim()}:null})
  if(!alive)return
  selected.value=r;showDraft.value=false;runs.value=[];runPage.value=1;query.value=r.id;remember(r.id);activationKey.value=crypto.randomUUID();canActivate.value=true;confirmation.value='';recurringAck.value=false;repeatAck.value=false;await list()
 }catch(e){fail(e)}finally{busy.value=false}
}
async function activate(){
 if(busy.value||!canActivate.value||uncertain.value)return
 error.value=''
 if(recurring.value&&!recurringAck.value){error.value='请确认周期性执行。';return}
 if(fullScope.value&&confirmation.value!==fullScope.value){error.value='请输入“'+fullScope.value+'”确认范围。';return}
 if(repeated.value&&!repeatAck.value){error.value='请确认同一账号按角色重复获得货币。';return}
 const id=selected.value.id;busy.value=true;uncertain.value=true;remember(id)
 try{selected.value=await api('/schedules/'+id+'/activate','POST',{fingerprint:selected.value.fingerprint,idempotency_key:activationKey.value,acknowledge_recurring:recurringAck.value,acknowledge_repeat:repeatAck.value,all_server_confirmation:confirmation.value});uncertain.value=false;canActivate.value=false;await list()}
 catch(e){if(e instanceof ApiError&&e.status<500)uncertain.value=false;fail(e)}finally{busy.value=false}
}
async function control(action:string){
 if(busy.value||uncertain.value)return
 error.value='';busy.value=true
 try{selected.value=await api('/schedules/'+selected.value.id+'/control','POST',{action,acknowledge_attention:attentionAck.value});attentionAck.value=false;await list()}
 catch(e){fail(e);error.value+=' 请刷新原计划核对，勿另建重复计划。'}finally{busy.value=false}
}
function copyPlan(){
 if(!selected.value||uncertain.value)return
 const d=selected.value.request
 showDraft.value=true;title.value=selected.value.title+'（副本）';kind.value=d.kind;first.value=shanghaiInput(Math.floor(Date.now()/1000)+3600);recurrence.value=d.recurrence;end.value='';seed.value=d.reward_job;draftKey.value++
 message.value=d.notice?.message||'';reason.value=d.notice?.reason||'';selected.value=null;canActivate.value=false;query.value='';runs.value=[];error.value='';fields.value={};try{sessionStorage.removeItem(storage)}catch{}
}
async function changePage(delta:number,history=false){if(busy.value)return;busy.value=true;try{if(history){runPage.value+=delta;await read(selected.value.id)}else{page.value+=delta;await list()}}catch(e){fail(e)}finally{busy.value=false}}
onMounted(async()=>{
 try{await list();const id=sessionStorage.getItem(storage);if(id)await read(id)}catch(e){fail(e)}
 timer=setInterval(()=>{if(document.hidden||busy.value||!selected.value)return;void inspect(selected.value.id)},30000)
})
onBeforeUnmount(()=>{alive=false;if(timer)clearInterval(timer)})
</script>
<template>
 <section class="schedules">
  <section class="panel">
   <div class="section-title"><h2>定时运营</h2><span class="pill">北京时间 UTC+8</span><button :disabled="busy||uncertain" @click="showDraft=!showDraft">{{showDraft?'收起编辑器':'创建新计划'}}</button></div>
   <p class="notice">计划到期时才冻结收件名单；错过超过5分钟的期次只记录跳过，不补发。每日／每周保持相同北京时间。</p>
   <p v-if="!workerEnabled" class="warning">定时执行器未启用。可以准备预览，但不能激活；已有计划不会自动执行。</p>
   <fieldset v-show="showDraft" :disabled="busy||uncertain">
    <div class="schedule-grid">
     <label>计划名称<input v-model="title" aria-label="计划名称" maxlength="100" :aria-invalid="!!fields.title"><small v-if="fields.title" role="alert" class="submit-error">{{fields.title}}</small></label>
     <label>计划类型<select v-model="kind" aria-label="计划类型"><option value="reward">定时奖励</option><option value="notice">定时公告</option></select></label>
     <label>首次执行（北京时间）<input v-model="first" type="datetime-local" aria-label="首次北京时间" :aria-invalid="!!fields.first"><small v-if="fields.first" role="alert" class="submit-error">{{fields.first}}</small></label>
     <label>执行周期<select v-model="recurrence" aria-label="执行周期"><option value="once">仅一次</option><option value="daily">每天</option><option value="weekly">每周</option></select></label>
     <label v-if="recurrence!=='once'">结束时间（可留空，北京时间）<input v-model="end" type="datetime-local" aria-label="结束北京时间"><small v-if="fields.end" role="alert" class="submit-error">{{fields.end}}</small></label>
    </div>
    <template v-if="kind==='notice'">
     <label>公告文字<textarea v-model="message" aria-label="定时公告文字" :aria-invalid="!!fields.message"/><small v-if="fields.message" class="submit-error" role="alert">{{fields.message}}</small></label>
     <label>公告原因<input v-model="reason" aria-label="定时公告原因" maxlength="200" :aria-invalid="!!fields.reason"><small v-if="fields.reason" class="submit-error" role="alert">{{fields.reason}}</small></label>
     <button class="primary" @click="preview()">预览定时公告计划</button>
    </template>
   </fieldset>
  </section>
  <fieldset v-if="kind==='reward'" v-show="showDraft" :disabled="busy||uncertain" class="reward-editor"><RewardJobs :key="draftKey" schedule-draft :initial-draft="seed" @schedule="preview" @reauth="emit('reauth')"/></fieldset>
  <p v-if="error&&showDraft" class="submit-error" role="alert">{{error}}</p>
  <section v-if="selected" class="panel" aria-label="计划预览与状态">
   <div class="section-title"><h2>{{selected.title}}</h2><span class="pill">{{labels[selected.status]||selected.status}}</span></div>
   <p class="break">计划编号：<code>{{selected.id}}</code></p>
   <p>首次：{{scheduleTime(selected.request.first_due)}} · {{({once:'仅一次',daily:'每天',weekly:'每周'} as Record<string,string>)[selected.request.recurrence]}}</p>
   <p>下一期：{{scheduleTime(selected.next_due)}}<span v-if="selected.request.end_at"> · 截止：{{scheduleTime(selected.request.end_at)}}</span></p>
   <p v-if="selected.last_error" class="submit-error" role="alert">{{selected.last_error}}</p>
   <p v-if="selected.kind==='notice'">公告：{{selected.request.notice.message}}</p>
   <template v-else>
    <p>预览时估算 {{selected.preview.estimate?.target_count}} 个角色、{{selected.preview.estimate?.account_count}} 个账号；不是本次实际名单。</p>
    <p>账号货币：{{selected.request.reward_job.account_reward_mode==='once_per_account'?'每账号一份':'每角色一份（同账号可能重复）'}}</p>
    <p v-for="(v,k) in selected.request.reward_job.reward.currency_rewards" :key="k">{{({cera:'点券',cera_point:'代币券',mileage:'积分'} as Record<string,string>)[k]}}：{{v}}／份</p>
    <p>邮件金币：{{selected.preview.binding.reward.gold}}／角色</p>
    <ul><li v-for="(item,n) in selected.preview.binding.reward.rewards.items" :key="n">{{item.name||'#'+item.id}} × {{item.quantity}}／角色</li></ul>
   </template>
   <p class="field-hint">{{selected.preview.note}}</p>
   <p v-if="error&&!showDraft" class="submit-error" role="alert">{{error}}</p>
   <template v-if="selected.status==='preview'&&canActivate">
    <label v-if="fullScope">输入“{{fullScope}}”确认范围<input v-model="confirmation" aria-label="定时全服确认" :disabled="busy||uncertain"></label>
    <label v-if="recurring" class="schedule-check"><input v-model="recurringAck" type="checkbox" :disabled="busy||uncertain">我确认按此周期重复执行，直到截止、暂停或取消</label>
    <label v-if="repeated" class="schedule-check"><input v-model="repeatAck" type="checkbox" :disabled="busy||uncertain">我确认同账号按角色数重复获得账号货币</label>
    <button class="primary" :disabled="busy||uncertain||!selected.worker_enabled" @click="activate">确认启用计划</button>
   </template>
   <p v-else-if="selected.status==='preview'" class="notice">恢复的预览只允许查询或取消；需要新计划请复制后重新预览，不自动重放激活请求。</p>
   <p v-if="uncertain" class="submit-error" role="alert">激活结果待确认。请只查询这个计划编号，不要另建重复计划。</p>
   <label v-if="selected.last_error&&['paused','needs_attention'].includes(selected.status)" class="schedule-check"><input v-model="attentionAck" type="checkbox">已核对异常记录；继续只影响后续期次，不补发异常期次</label>
   <div class="toolbar">
    <button :disabled="busy" @click="inspect(selected.id)">刷新原计划（只读）</button>
    <button v-if="selected.status==='active'" :disabled="busy||uncertain" @click="control('pause')">暂停后续期次</button>
    <button v-if="['paused','needs_attention'].includes(selected.status)&&selected.next_due" :disabled="busy||uncertain" @click="control('resume')">继续后续期次</button>
    <button v-if="!['completed','cancelled'].includes(selected.status)" :disabled="busy||uncertain" @click="control('cancel')">取消后续期次</button>
    <button :disabled="busy||uncertain" @click="copyPlan">复制为新计划草稿</button>
   </div>
   <p class="warning">暂停／取消只影响尚未触发的期次；已创建的奖励任务需单独暂停或取消，已经发出的公告和奖励不会撤销。</p>
   <h3>执行记录</h3>
   <div v-if="!runs.length" class="empty">尚无执行记录</div>
   <article v-for="run in runs" :key="run.id" class="schedule-run">
    <strong>{{labels[run.status]||run.status}}</strong>
    <p>计划时刻：{{scheduleTime(run.due_at)}} · 实际触发／核对：{{scheduleTime(run.started_at)}}</p>
    <p v-if="run.skipped_count">共跳过 {{run.skipped_count}} 期，最后一期 {{scheduleTime(run.last_due_at)}}</p>
    <p v-if="run.error_message">{{run.error_message}}</p>
    <button v-if="run.reference_id" @click="emit('child',run.reference_kind,run.reference_id)">查看原{{run.reference_kind==='reward'?'奖励任务':'公告操作'}}</button>
    <code v-if="run.reference_id" class="break">{{run.reference_id}}</code>
   </article>
   <div class="pagination"><button :disabled="busy||runPage===1" @click="changePage(-1,true)">上一页执行记录</button><span>{{runPage}}</span><button :disabled="busy||runs.length<50" @click="changePage(1,true)">下一页执行记录</button></div>
  </section>
  <p v-if="error&&!selected&&!showDraft" class="submit-error" role="alert">{{error}}</p>
  <section class="panel">
   <div class="section-title"><h2>计划列表</h2><button :disabled="busy" @click="changePage(0)">刷新列表</button></div>
   <form class="toolbar" @submit.prevent="inspect()"><label>查询原计划编号<input v-model="query" aria-label="原计划编号"></label><button :disabled="busy">查询计划</button></form>
   <div v-if="!items.length" class="empty">暂无计划</div>
   <button v-for="item in items" :key="item.id" class="schedule-list-item" :disabled="busy||uncertain" @click="inspect(item.id)"><strong>{{item.title}}</strong><span>{{labels[item.status]||item.status}} · {{scheduleTime(item.next_due)}}</span></button>
   <div class="pagination"><button :disabled="busy||page===1" @click="changePage(-1)">上一页计划</button><span>{{page}}</span><button :disabled="busy||items.length<50" @click="changePage(1)">下一页计划</button></div>
  </section>
 </section>
</template>
<style scoped>
.schedules{display:grid;gap:18px;min-width:0}.schedule-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}fieldset{border:0;padding:0;min-width:0}.schedule-check{display:flex;flex-direction:row;align-items:flex-start;gap:10px;margin:14px 0}.schedule-check input{width:auto;flex:0 0 auto}.schedule-run{border-top:1px solid var(--border-color);padding:14px 0;overflow-wrap:anywhere}.schedule-list-item{display:flex;width:100%;justify-content:space-between;gap:12px;margin:8px 0;text-align:left}.schedule-list-item span{color:var(--text-secondary)}.break{overflow-wrap:anywhere}.schedules input,.schedules select,.schedules textarea{min-width:0;max-width:100%}.reward-editor{margin:0}.schedules .toolbar{flex-wrap:wrap}.schedules .toolbar label{flex:1 1 280px}.schedules .toolbar label input{flex:0 0 auto}@media(max-width:640px){.schedule-grid{grid-template-columns:1fr}.schedule-list-item{flex-direction:column}.schedule-run button{width:100%}}
</style>
