<script setup lang="ts">
import {computed,onMounted,onBeforeUnmount,ref,watch} from 'vue'
import {api,ApiError,uncertainMessage} from '../api'
import {useGmConfirmation} from '../stores/gm/confirmation'
const props=defineProps<{initialCampaign?:string}>()
const emit=defineEmits<{reauth:[],batch:[draft:any],schedule:[draft:any],inspect:[id:string],navigate:[target:{page:'reward-jobs'|'schedules',id:string}]}>()
const lease=useGmConfirmation(),items=ref<any[]>([]),selected=ref<any>(null),page=ref(1),more=ref(false),search=ref(''),filter=ref('')
const busy=ref(false),error=ref(''),schema=ref<any>(null),preview=ref<any>(null),uncertain=ref(false),cancelling=ref(false),requestKey=ref(''),notice=ref('')
const name=ref(''),description=ref(''),status=ref('draft'),dedupe=ref('account'),reason=ref(''),mode=ref('filtered'),ids=ref(''),tags=ref(''),job=ref(''),minimum=ref(1),maximum=ref(255),createdFrom=ref(''),createdTo=ref(''),inactiveBefore=ref('')
const templateQuery=ref(''),templates=ref<any[]>([]),templateId=ref(0),templateVersion=ref(1),versions=ref<any[]>([])
const immutable=computed(()=>!!selected.value?.activated),dateAvailable=computed(()=>!!schema.value?.character_dates?.available)
const labels:Record<string,string>={draft:'草稿',active:'进行中',paused:'已暂停',archived:'已归档'}
const storage='dnfgm.campaign-operation'
let alive=true
let openEpoch=0,queuedOpen=''
function fail(e:unknown){error.value=uncertainMessage(e);if(e instanceof ApiError&&e.status===403&&e.message.includes('认证'))emit('reauth')}
function remember(){sessionStorage.setItem(storage,JSON.stringify({id:preview.value?.operation_id,key:requestKey.value,uncertain:uncertain.value,cancelling:cancelling.value}))}
async function list(){const r=await api(`/campaigns?page=${page.value}&status=${filter.value}&q=${encodeURIComponent(search.value)}`);if(alive){items.value=r.items;more.value=r.has_more}}
function apply(row:any){
 selected.value=row;preview.value=null;notice.value='';const d=row.definition,t=d.targets
 name.value=d.name;description.value=d.description;status.value=row.status;dedupe.value=d.dedupe;reason.value=''
 mode.value=t.mode;ids.value=(t.mode==='accounts'?t.account_uids:t.charac_nos||[]).join('\n');tags.value=(t.tags_all||[]).join(', ');job.value=t.job==null?'':String(t.job);minimum.value=t.min_level;maximum.value=t.max_level
 createdFrom.value=t.created_from||'';createdTo.value=t.created_to||'';inactiveBefore.value=t.inactive_before||'';templateId.value=d.template_id;templateVersion.value=d.template_version;versions.value=[]
}
async function open(id:string){if(busy.value||uncertain.value||preview.value)return;const epoch=++openEpoch;busy.value=true;error.value='';try{const r=await api('/campaigns/'+id);if(alive&&epoch===openEpoch)apply(r)}catch(e){if(alive&&epoch===openEpoch)fail(e)}finally{busy.value=false}}
function flushQueuedOpen(){
 if(busy.value||!queuedOpen)return
 const id=queuedOpen;queuedOpen=''
 if(preview.value||uncertain.value){notice.value='当前活动仍有待确认或待核对的原操作，已保留原编号。请先核对或取消，再切换活动。';return}
 if(id!==selected.value?.id)void open(id)
}
function reset(){if(busy.value||uncertain.value||preview.value)return;sessionStorage.removeItem(storage);lease.release('campaigns');selected.value=null;preview.value=null;name.value='';description.value='';status.value='draft';dedupe.value='account';reason.value='';mode.value='filtered';ids.value='';tags.value='';job.value='';minimum.value=1;maximum.value=255;createdFrom.value='';createdTo.value='';inactiveBefore.value='';templateId.value=0;templateVersion.value=1;versions.value=[];error.value='';notice.value=''}
function audience(){
 if(immutable.value)return selected.value.definition.targets
 if(mode.value==='all')return {mode:'all'}
 if(mode.value==='selected'||mode.value==='accounts'){
  const values=ids.value.split(/[\s,，;；]+/).filter(Boolean)
  if(!values.length||values.length>5000||values.some(v=>!/^\d+$/.test(v)||Number(v)<1||Number(v)>2147483647))throw new Error('请填写1至5000个有效编号。')
  return {mode:mode.value,[mode.value==='accounts'?'account_uids':'charac_nos']:values.map(Number)}
 }
 return {mode:mode.value,job:job.value===''?null:Number(job.value),min_level:minimum.value,max_level:maximum.value,
  tags_all:tags.value.split(/[,，;；\n]+/).map(v=>v.trim()).filter(Boolean),created_from:createdFrom.value||null,created_to:createdTo.value||null,inactive_before:inactiveBefore.value||null}
}
async function findTemplates(){if(busy.value)return;busy.value=true;error.value='';try{templates.value=(await api('/gift-templates?q='+encodeURIComponent(templateQuery.value))).items}catch(e){fail(e)}finally{busy.value=false}}
async function chooseTemplate(t:any){templateId.value=t.id;templateVersion.value=t.current_version;error.value='';try{versions.value=(await api('/gift-templates/'+t.id+'/versions')).items}catch(e){fail(e)}}
async function prepare(){
 if(busy.value||uncertain.value||preview.value)return;error.value='';notice.value=''
 try{
  if(!name.value.trim())throw new Error('请填写活动名称。')
  if(!reason.value.trim())throw new Error('请填写操作原因。')
  if(!templateId.value)throw new Error('请选择来源礼包及固定版本。')
  const targets=audience()
  if(!lease.acquire('campaigns'))throw new Error('请先完成或关闭当前确认面板。')
  busy.value=true
  const r=await api('/campaigns/preview','POST',{campaign_id:selected.value?.id||null,expected_revision:selected.value?.revision||0,name:name.value.trim(),description:description.value,status:status.value,dedupe:dedupe.value,targets,template_id:templateId.value,template_version:templateVersion.value,reason:reason.value.trim()})
  if(!alive)return;preview.value=r;requestKey.value=crypto.randomUUID();uncertain.value=false;remember()
 }catch(e){fail(e);if(!preview.value)lease.release('campaigns')}finally{busy.value=false}
}
async function confirm(){
 if(busy.value||uncertain.value||!preview.value||preview.value.confirmable===false)return;error.value='';busy.value=true
 try{
  if(!lease.acquire('campaigns'))throw new Error('请先完成或关闭当前确认面板。')
  uncertain.value=true;remember()
  const r=await api('/campaigns/operations/'+preview.value.operation_id+'/confirm','POST',{idempotency_key:requestKey.value})
  uncertain.value=false;sessionStorage.removeItem(storage);lease.release('campaigns');apply(await api('/campaigns/'+r.campaign_id));await list();notice.value='活动已保存；没有自动发放奖励或启动计划。'
 }catch(e){if(e instanceof ApiError&&e.status<500){uncertain.value=false;remember()}fail(e)}finally{busy.value=false}
}
async function inspect(){
 if(busy.value||!preview.value)return;busy.value=true;error.value=''
 try{const r=await api('/campaigns/operations/'+preview.value.operation_id);await recover(r)}catch(e){fail(e)}finally{busy.value=false}
}
async function recover(r:any){
 preview.value=r;cancelling.value=false
 if(r.status==='committed'){uncertain.value=false;sessionStorage.removeItem(storage);lease.release('campaigns');apply(await api('/campaigns/'+r.result.campaign_id));await list();notice.value='已按原编号核对活动保存结果。'}
 else if(r.status==='cancelled'){uncertain.value=false;sessionStorage.removeItem(storage);lease.release('campaigns');preview.value=null;notice.value='原活动预览已取消，记录和原编号保留在审计中；没有发放奖励。'}
 else if(r.status==='preview'){remember();notice.value=uncertain.value?'原操作目前仍是预览，先前提交结果仍需核对；可显式取消原预览，不能重复确认。':r.confirmable===false?'此预览属于先前登录或已过期。当前会话只核对；取消原预览后可重新修改。':'原预览目前仍待确认。可继续确认同一编号，或取消原预览后修改。'}
}
async function refreshList(){if(busy.value)return;busy.value=true;error.value='';try{await list()}catch(e){fail(e)}finally{busy.value=false}}
async function paginate(delta:number){page.value+=delta;await refreshList()}
async function paginateLinks(delta:number){
 if(busy.value||uncertain.value||preview.value||!selected.value)return;busy.value=true;error.value=''
 try{const r=await api('/campaigns/'+selected.value.id+'?page='+((selected.value.page||1)+delta));if(alive)selected.value={...selected.value,links:r.links,page:r.page,has_more:r.has_more}}
 catch(e){fail(e)}finally{busy.value=false}
}
async function discard(){
 if(busy.value||cancelling.value||!preview.value||(uncertain.value&&preview.value.status!=='preview'))return;busy.value=true;error.value='';uncertain.value=true;cancelling.value=true;remember()
 try{await recover(await api('/campaigns/operations/'+preview.value.operation_id+'/cancel','POST'))}
 catch(e){if(e instanceof ApiError&&e.status<500){uncertain.value=false;cancelling.value=false;remember()}fail(e)}finally{busy.value=false}
}
onMounted(async()=>{
 try{const [r]=await Promise.all([api('/campaigns/audience-schema'),list()]);if(!alive)return;schema.value=r;const saved=JSON.parse(sessionStorage.getItem(storage)||'null');if(saved&&/^[a-f0-9]{32}$/.test(saved.id)){preview.value={operation_id:saved.id};requestKey.value=saved.key;uncertain.value=!!saved.uncertain;cancelling.value=!!saved.cancelling;await inspect()}else if(props.initialCampaign){await open(props.initialCampaign)}}catch(e){fail(e)}
})
watch(()=>props.initialCampaign,id=>{
 if(!id||id===selected.value?.id)return
 if(preview.value||uncertain.value){notice.value='当前活动仍有待确认或待核对的原操作，已保留原编号。请先核对或取消，再切换活动。';return}
 openEpoch++;queuedOpen=id;flushQueuedOpen()
})
watch(busy,value=>{if(!value)flushQueuedOpen()})
onBeforeUnmount(()=>{alive=false;lease.release('campaigns')})
</script>
<template>
 <section class="campaigns">
  <section class="panel">
   <div class="section-title"><h2>活动运营</h2><button :disabled="busy||uncertain||!!preview" @click="reset">新建活动</button></div>
   <p class="field-hint">一个活动固定礼包版本与人群。每账号或每角色只能提交一次完整奖励，手动、批量和计划共用同一领取记录。</p>
   <div class="campaign-filters"><label>查找活动<input v-model="search" aria-label="查找活动"></label><label>活动状态<select v-model="filter" aria-label="活动状态筛选"><option value="">全部</option><option v-for="(label,key) in labels" :key="key" :value="key">{{label}}</option></select></label><button :disabled="busy" @click="page=1;refreshList()">查询活动</button></div>
   <div class="campaign-list"><button v-for="row in items" :key="row.id" :disabled="busy||uncertain||!!preview" @click="open(row.id)"><strong>{{row.name}}</strong><span>{{labels[row.status]}} · 修订 {{row.revision}}</span></button><p v-if="!items.length">没有符合条件的活动。</p></div>
   <div class="actions"><button :disabled="busy||page===1" @click="paginate(-1)">上一页</button><span>第 {{page}} 页</span><button :disabled="busy||!more" @click="paginate(1)">下一页</button></div>
  </section>
  <form class="panel" @submit.prevent="prepare">
   <div class="section-title"><h2>{{selected?'管理活动':'新活动草稿'}}</h2><span v-if="selected" class="pill">{{labels[selected.status]}}</span></div>
   <p v-if="immutable" class="notice">已启用的礼包、人群和去重规则固定。可以暂停、恢复或归档；修改内容请新建活动。归档保留全部领取和审计。</p>
   <fieldset :disabled="busy||uncertain||!!preview">
    <fieldset :disabled="immutable" class="campaign-grid">
     <label>活动名称<input v-model="name" aria-label="活动名称" maxlength="80" required></label>
     <label>领取口径<select v-model="dedupe" aria-label="活动领取口径"><option value="account">每活动每账号一次整份礼包</option><option value="character">每活动每角色一次整份礼包</option></select></label>
     <label class="full">活动说明<textarea v-model="description" aria-label="活动说明" maxlength="1000"/></label>
     <label>礼包搜索<input v-model="templateQuery" aria-label="活动礼包搜索"><button type="button" @click="findTemplates">查找礼包</button></label>
     <div><p>固定礼包 #{{templateId||'未选择'}} · 版本 {{templateVersion}}</p><button v-for="t in templates" :key="t.id" type="button" @click="chooseTemplate(t)">{{t.name}} #{{t.id}}</button><label v-if="versions.length">固定版本<select v-model.number="templateVersion" aria-label="活动礼包固定版本"><option v-for="v in versions" :key="v.version" :value="v.version">版本 {{v.version}}</option></select></label></div>
     <label>保存人群<select v-model="mode" aria-label="活动人群"><option value="filtered">按条件</option><option value="selected">指定角色编号</option><option value="accounts">指定账号 UID</option><option value="online">在线账号下的角色</option><option value="all">全部未删除角色</option></select></label>
     <label v-if="mode==='selected'||mode==='accounts'" class="full">编号名单<textarea v-model="ids" aria-label="活动编号名单" placeholder="每行一个编号"/></label>
     <template v-if="mode==='filtered'||mode==='online'">
      <label>基础职业编号<input v-model="job" type="number" min="0" max="255" aria-label="活动职业编号" placeholder="全部职业"></label>
      <label>最低等级<input v-model.number="minimum" type="number" min="0" max="255" aria-label="活动最低等级"></label><label>最高等级<input v-model.number="maximum" type="number" min="0" max="255" aria-label="活动最高等级"></label>
      <label class="full">账号标签（须全部匹配）<input v-model="tags" aria-label="活动玩家标签" placeholder="例如：回归, 公会活动"></label>
      <label>角色创建起日<input v-model="createdFrom" type="date" aria-label="角色创建起日" :disabled="!dateAvailable"></label><label>角色创建止日<input v-model="createdTo" type="date" aria-label="角色创建止日" :disabled="!dateAvailable"></label>
      <label>最后游玩早于<input v-model="inactiveBefore" type="date" aria-label="最后游玩早于" :disabled="!dateAvailable"></label>
      <p class="field-hint full">{{schema?.character_dates?.note||'正在核对角色日期字段与只读权限。'}} {{schema?.returning?.note}} 角色创建日不是账号注册日。</p>
     </template>
    </fieldset>
    <div class="campaign-grid"><label>保存后状态<select v-model="status" aria-label="活动保存状态"><option value="draft" :disabled="immutable">草稿</option><option value="active">进行中</option><option value="paused" :disabled="!selected">暂停</option><option value="archived" :disabled="!selected">归档</option></select></label><label>操作原因<input v-model="reason" aria-label="活动操作原因" maxlength="200" required></label></div>
    <button class="primary" type="submit" :disabled="selected?.status==='archived'">预览活动变更</button>
   </fieldset>
  </form>
  <section v-if="preview" class="panel" aria-label="活动变更预览">
   <h2>核对活动变更</h2><p class="break">原操作编号：<code>{{preview.operation_id}}</code></p>
   <template v-if="preview.preview"><p>{{preview.preview.definition.name}} · {{labels[preview.preview.status]}} · {{preview.preview.definition.dedupe==='account'?'每账号一次':'每角色一次'}}整份礼包</p><p>礼包 #{{preview.preview.definition.template_id}} 版本 {{preview.preview.definition.template_version}}</p><p v-for="(v,k) in preview.preview.reward.currency_rewards" :key="k">{{({cera:'点券',cera_point:'代币券',mileage:'商城积分'} as Record<string,string>)[k]}}：{{v}}</p><p>邮件金币：{{preview.preview.reward.gold}}</p><ul><li v-for="i in preview.preview.binding.snapshot.rewards.items" :key="i.id">{{i.name}} × {{i.quantity}}</li></ul><p class="notice">{{preview.preview.note}}</p></template>
   <p v-if="uncertain" role="status" class="warning">保存结果待核对。仅查询原编号，不新建或重复确认。</p>
   <p v-if="preview.confirmable===false&&preview.status==='preview'" class="notice">当前登录不能确认这份预览。取消会先锁定原操作；已经保存的活动只返回原结果，不会撤销或重放。</p>
   <div class="actions"><button type="button" :disabled="busy" @click="inspect">核对原操作（只读）</button><button v-if="!cancelling&&(!uncertain||preview.status==='preview')" type="button" :disabled="busy" @click="discard">{{preview.confirmable===false||uncertain?'取消原预览并返回修改':'返回修改'}}</button><button v-if="!uncertain&&preview.confirmable!==false" class="primary" type="button" :disabled="busy" @click="confirm">确认保存活动</button></div>
  </section>
  <section v-if="selected" class="panel" aria-label="活动记录与统计">
   <div class="section-title"><h2>领取与关联记录</h2><span>已提交 {{selected.claims.subjects}} 份 · {{selected.claims.accounts}} 个账号</span></div>
   <p class="notice">{{selected.note}}</p><div class="actions"><button :disabled="busy||uncertain||selected.status!=='active'" @click="emit('batch',selected.job_draft)">准备本活动批量发放</button><button :disabled="busy||uncertain||selected.status!=='active'" @click="emit('schedule',selected.job_draft)">准备本活动定时计划</button></div>
   <ul><li v-for="(t,index) in selected.totals" :key="index">{{t.metric==='item'?(t.item_name||'#'+t.item_id):({cera:'点券',cera_point:'代币券',mileage:'商城积分',gold:'邮件金币'} as Record<string,string>)[t.metric]}}：{{t.amount}}</li></ul><p v-if="selected.totals_truncated" class="field-hint">这里只显示前50种统计项。</p>
   <div class="table-wrap"><table><thead><tr><th>类型</th><th>原编号</th><th>状态</th></tr></thead><tbody><tr v-for="link in selected.links" :key="link.kind+link.reference_id"><td>{{({job:'批量任务',schedule:'计划',reward:'奖励操作'} as Record<string,string>)[link.kind]}}</td><td class="break"><code>{{link.reference_id}}</code><button v-if="link.kind==='reward'" @click="emit('inspect',link.reference_id)">查看原操作</button><button v-else-if="link.kind==='job'" @click="emit('navigate',{page:'reward-jobs',id:link.reference_id})">查看批量任务</button><button v-else-if="link.kind==='schedule'" @click="emit('navigate',{page:'schedules',id:link.reference_id})">查看定时计划</button></td><td>{{link.status}}</td></tr></tbody></table></div>
   <div class="actions"><button :disabled="busy||uncertain||!!preview||(selected.page||1)===1" @click="paginateLinks(-1)">记录上一页</button><span>记录第 {{selected.page||1}} 页</span><button :disabled="busy||uncertain||!!preview||!selected.has_more" @click="paginateLinks(1)">记录下一页</button></div>
  </section>
  <p v-if="error" class="submit-error" role="alert">{{error}}</p><p v-if="notice" role="status" class="success">{{notice}}</p>
 </section>
</template>
<style scoped>
.campaigns{display:grid;gap:var(--gap,16px)}.campaign-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;border:0;padding:0;margin-bottom:16px}.full{grid-column:1/-1}.campaign-filters{display:flex;align-items:end;flex-wrap:wrap;gap:12px}.campaign-list{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px;margin:16px 0}.campaign-list>button{display:flex;flex-direction:column;align-items:start;gap:6px;text-align:left;padding:14px}.campaign-list span{font-size:12px;opacity:.75}.campaigns fieldset{min-width:0}.campaigns label{display:grid;gap:6px}.campaigns .table-wrap{overflow:auto}.campaigns td{max-width:380px}@media(max-width:640px){.campaign-grid{grid-template-columns:1fr}.full{grid-column:auto}.campaign-filters{align-items:stretch;flex-direction:column}.campaign-list{grid-template-columns:1fr}.campaigns .actions{flex-wrap:wrap}}
</style>
