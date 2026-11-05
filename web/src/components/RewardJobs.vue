<script setup lang="ts">
import {ref,computed,onMounted,onBeforeUnmount,watch} from 'vue'
import {api,ApiError,uncertainMessage} from '../api'
import ItemQueue from './ItemQueue.vue'
import CharacterPicker from './CharacterPicker.vue'
import {mailTextErrors} from '../validation'
const props=defineProps<{scheduleDraft?:boolean,initialDraft?:any,initialJob?:string}>()
const emit=defineEmits<{reauth:[],inspect:[id:string],schedule:[draft:any],opened:[]}>()
const accountKind=ref('uid'),accountList=ref(''),importNotice=ref('')
const mode=ref('selected'),ids=ref(''),uid=ref(''),jobFilter=ref(''),minimum=ref(0),maximum=ref(255),name=ref('')
watch([accountKind,mode],()=>{importNotice.value=''})
const rewardMode=ref('once_per_account'),reason=ref(''),gold=ref(0),message=ref('GM rewards'),amounts=ref<Record<string,number>>({cera:0,cera_point:0,mileage:0})
const mailTitle=ref('')
const currencyNames:Record<string,string>={cera:'点券',cera_point:'代币券',mileage:'商城积分'}
const items=ref<any[]>([]),query=ref(''),found=ref<any[]>([]),templateQuery=ref(''),templates=ref<any[]>([]),template=ref<any>(null)
const adjusted=ref(false)
function selectTemplate(g:any){template.value=g;adjustTemplate();adjusted.value=false}
function adjustTemplate(){const r=template.value.rewards;if(!r)return;items.value=r.items.map((i:any)=>({...i}));gold.value=r.gold||0;message.value=r.message??'GM rewards';mailTitle.value=r.mail_title??'';amounts.value={cera:0,cera_point:0,mileage:0,...r.currency_rewards};adjusted.value=true}
const selected=ref<any>(null),targets=ref<any[]>([]),next=ref<number|null>(null),cursor=ref(0),previous=ref<number[]>([])
const jobs=ref<any[]>([]),page=ref(1),more=ref(false),busy=ref(false),error=ref(''),lookupError=ref(''),searchError=ref(''),notice=ref('')
const fieldErrors=ref<Record<string,string>>({}),confirmation=ref(''),repeat=ref(false),uncertain=ref(false),pendingId=ref(''),key=ref('')
const checked=ref(''),queryId=ref(''),draftVisible=ref(true)
const labels:Record<string,string>={preview:'待确认预览',pending:'等待执行',running:'执行中',executing:'单角色提交中',committed:'数据库已提交',uncertain:'提交待核对',paused:'已暂停',cancelled:'已取消剩余目标',failed:'未提交／需处理',finished:'全部数据库提交',needs_attention:'需要处理'}
let timer:ReturnType<typeof setInterval>|undefined,alive=true
const storage='dnfgm.pending-reward-job'
function persist(){try{sessionStorage.setItem(storage,JSON.stringify({id:pendingId.value,key:key.value,uncertain:uncertain.value}))}catch{}}
function fail(e:unknown){error.value=uncertainMessage(e);if(e instanceof ApiError&&e.status===403&&error.value.includes('认证'))emit('reauth')}
function integer(v:unknown,lo:number,hi:number){return typeof v==='number'&&Number.isSafeInteger(v)&&v>=lo&&v<=hi}
function parseIds(){const parts=ids.value.trim().split(/[\s,，;；]+/).filter(Boolean);if(!parts.length||parts.length>5000||parts.some(v=>!/^\d+$/.test(v)||!integer(Number(v),1,2147483647)))throw new Error('填写1至5000个有效角色编号，用空格、逗号或换行分隔。');return parts.map(Number)}
function parseAccounts():number[]|string[]{
 const parts=accountList.value.trim().split(/[\r\n,，;；]+/).map(v=>v.trim()).filter(Boolean)
 const max=accountKind.value==='uid'?5000:1000
 if(!parts.length||parts.length>max)throw new Error('请填写1至'+max+'个账号，每行一个，不含表头。')
 if(accountKind.value==='uid'){
  if(parts.some(v=>!/^\d+$/.test(v)||!integer(Number(v),1,2147483647)))throw new Error('账号 UID 须为1至2,147,483,647的整数；每行一个。')
  return parts.map(Number)
 }
 if(parts.some(v=>Array.from(v).length>255||/[\x00-\x1f\x7f]/.test(v)))throw new Error('账号名不能超过255个字符或包含控制字符。')
 return parts
}
async function importAccounts(event:Event){const input=event.target as HTMLInputElement;const file=input.files?.[0];if(!file)return;importNotice.value='';try{if(file.size>262144)throw new Error('名单文件不能超过256 KiB。');accountList.value=await file.text();parseAccounts();fieldErrors.value={};importNotice.value='账号名单已读入草稿；预览时核对账号，没有发放奖励。'}catch(e){fieldErrors.value={accounts:uncertainMessage(e)}}finally{input.value=''}}
async function importIds(event:Event){const input=event.target as HTMLInputElement;const file=input.files?.[0];if(!file)return;importNotice.value='';try{if(file.size>262144)throw new Error('名单文件不能超过256 KiB。');ids.value=await file.text();parseIds();fieldErrors.value={};importNotice.value='名单已读入本地草稿，没有上传文件或发放奖励。'}catch(e){fieldErrors.value={ids:uncertainMessage(e)}}finally{input.value=''}}
function payload(){
 const errors:Record<string,string>={};let list:number[]=[],accounts:number[]|string[]=[]
 if(!reason.value.trim())errors.reason='请填写发放原因。'
 if(mode.value==='selected'){try{list=parseIds()}catch(e){errors.ids=uncertainMessage(e)}}
 if(mode.value==='accounts'){try{accounts=parseAccounts()}catch(e){errors.accounts=uncertainMessage(e)}}
 if(mode.value!=='selected'&&mode.value!=='all'&&mode.value!=='accounts'){
  if(uid.value&&!/^\d+$/.test(uid.value))errors.filters='账号 UID 应为正整数。'
  if(uid.value&&!integer(Number(uid.value),1,2147483647))errors.filters='账号 UID 超出范围。'
  if(jobFilter.value&&!integer(Number(jobFilter.value),0,255))errors.filters='职业编号应为0至255的整数。'
  if(!integer(minimum.value,0,255)||!integer(maximum.value,0,255)||minimum.value>maximum.value)errors.filters='请填写正确的等级范围。'
  if(mode.value==='filtered'&&!uid.value&&!jobFilter.value&&!name.value.trim()&&minimum.value===0&&maximum.value===255)errors.filters='请填写筛选条件，或明确选择全服角色。'
 }
 if(!template.value||adjusted.value){
  Object.assign(errors,mailTextErrors(mailTitle.value,message.value,'batch'))
  for(const [k,v] of Object.entries(amounts.value))if(!integer(v,0,1000000000))errors.reward=currencyNames[k]+'须为0至10亿的整数。'
  if(!integer(gold.value,0,1000000000))errors.reward='金币附件须为0至10亿的整数。'
  items.value.forEach((item,n)=>{if(!integer(item.quantity,1,2147483647))errors['batch-quantity-'+n]='数量须为1至2,147,483,647的整数。'})
  if(!items.value.length&&!gold.value&&!Object.values(amounts.value).some(Boolean))errors.reward='至少添加一项账号货币、金币或物品奖励。'
 }
 fieldErrors.value=errors;if(Object.keys(errors).length)throw new Error('请修正对应输入项旁的提示。')
 const filters=mode.value==='accounts'?{mode:'accounts',[accountKind.value==='uid'?'account_uids':'account_names']:accounts}:mode.value==='selected'?{mode:mode.value,charac_nos:list}:mode.value==='all'?{mode:'all'}:{mode:mode.value,uid:Number(uid.value)||0,job:jobFilter.value===''?null:Number(jobFilter.value),min_level:minimum.value,max_level:maximum.value,q:name.value.trim()}
 const contents={items:items.value.map(({id,quantity})=>({id,quantity})),gold:gold.value,message:message.value,mail_title:mailTitle.value,currency_rewards:amounts.value}
 const reward=template.value?{template_id:template.value.id,template_version:template.value.current_version,...(adjusted.value?{template_overrides:contents}:{})}:contents
 return {targets:filters,reward,account_reward_mode:rewardMode.value,reason:reason.value.trim()}
}
async function list(){try{const r=await api('/reward-jobs?page='+page.value);if(!alive)return;jobs.value=r.items;more.value=r.has_more}catch(e){if(alive)lookupError.value=uncertainMessage(e)}}
async function loadTargets(after=0){if(!selected.value)return;const id=selected.value.id;const r=await api('/reward-jobs/'+id+'/targets?after='+after);if(alive&&selected.value?.id===id){targets.value=r.items;next.value=r.next_after;cursor.value=after}}
async function inspect(id:string,reset=true){
 if(!/^[a-f0-9]{32}$/.test(id)){lookupError.value='任务编号须为32位小写十六进制字符。';return}
 const r=await api('/reward-jobs/'+id);if(!alive)return;selected.value=r;queryId.value=id;checked.value=new Date().toLocaleTimeString('zh-CN');lookupError.value=''
 if(pendingId.value===id&&r.status!=='preview'){uncertain.value=false;persist()}
 if(reset){previous.value=[];await loadTargets(0)}else await loadTargets(cursor.value)
}
async function queryOriginal(){if(busy.value)return;busy.value=true;try{await inspect(queryId.value||pendingId.value,false);await list()}catch(e){lookupError.value=uncertainMessage(e)}finally{busy.value=false}}
async function choose(id:string){if(busy.value||uncertain.value)return;busy.value=true;error.value='';notice.value='';try{await inspect(id);confirmation.value='';repeat.value=false}catch(e){lookupError.value=uncertainMessage(e)}finally{busy.value=false}}
async function preview(){
 if(busy.value||uncertain.value)return;error.value='';notice.value='';let data;try{data=payload()}catch(e){fail(e);return}
 if(props.scheduleDraft){emit('schedule',data);return}
 busy.value=true
 try{const r=await api('/reward-jobs/preview','POST',data);selected.value=r;pendingId.value=r.id;queryId.value=r.id;key.value=crypto.randomUUID();uncertain.value=false;persist();confirmation.value='';repeat.value=false;previous.value=[];await loadTargets();await list();notice.value='名单和奖励已固定。请核对下方预览后启动；修改上方草稿不会改变这份预览。'}catch(e){fail(e)}finally{busy.value=false}
}
const repeatNeeded=computed(()=>selected.value?.request.account_reward_mode==='per_character'&&Object.keys(selected.value?.request.reward.currency_rewards||{}).length>0)
async function start(){
 if(busy.value||uncertain.value||!selected.value)return;error.value='';notice.value=''
 if(selected.value.request.targets.mode==='all'&&confirmation.value!=='全服发放'){error.value='请在启动按钮上方输入“全服发放”。';return}
 if(repeatNeeded.value&&!repeat.value){error.value='请确认同一账号将按选中角色数重复获得账号货币。';return}
 const j=selected.value
 if(pendingId.value!==j.id){pendingId.value=j.id;key.value=crypto.randomUUID()}
 uncertain.value=true;persist();busy.value=true
 try{selected.value=await api('/reward-jobs/'+j.id+'/start','POST',{fingerprint:j.fingerprint,target_count:j.target_count,account_count:j.account_count,idempotency_key:key.value,all_server_confirmation:confirmation.value,acknowledge_repeat:repeat.value});uncertain.value=false;persist();notice.value='任务已启动；关闭网页不会取消任务。数据库提交不代表客户端已领取。';await list()}
 catch(e){if(e instanceof ApiError&&e.status<500){uncertain.value=false;persist()}fail(e)}finally{busy.value=false}
}
async function control(action:string){if(busy.value||uncertain.value||!selected.value)return;busy.value=true;error.value='';notice.value='';try{selected.value=await api('/reward-jobs/'+selected.value.id+'/control','POST',{action});await loadTargets(cursor.value);await list();notice.value=action==='retry-failed'?'已重新排队确认未提交的目标；仍处于暂停，需要手动继续。':'任务状态已更新；已提交的奖励不撤销。'}catch(e){fail(e);error.value+=' 请刷新原任务核对状态，不要另建重复任务。'}finally{busy.value=false}}
async function findItems(){searchError.value='';try{found.value=(await api('/catalog?q='+encodeURIComponent(query.value)+'&page=1')).items}catch(e){searchError.value=uncertainMessage(e)}}
async function findTemplates(){searchError.value='';try{templates.value=(await api('/gift-templates?q='+encodeURIComponent(templateQuery.value)+'&page=1')).items}catch(e){searchError.value=uncertainMessage(e)}}
function add(item:any){if(items.value.length>=20){searchError.value='最多20条物品配置。';return}if(!item.sendable&&item.sendable!==undefined){searchError.value=item.policy_reason||'该物品已停用。';return}items.value.push({...item,quantity:1});searchError.value=''}
async function move(nextPage:boolean){const after=nextPage?next.value:previous.value.pop();if(after==null)return;if(nextPage)previous.value.push(cursor.value);busy.value=true;try{await loadTargets(after)}catch(e){lookupError.value=uncertainMessage(e)}finally{busy.value=false}}
watch(()=>props.initialDraft,d=>{
 if(!d)return
 const t=d.targets,r=d.reward.template_overrides||d.reward
 adjusted.value=!!d.reward.template_overrides
 accountKind.value=t.account_names?.length?'name':'uid';accountList.value=(t.account_names?.length?t.account_names:(t.account_uids||[])).join('\n')
 mode.value=t.mode;ids.value=(t.charac_nos||[]).join(', ');uid.value=t.uid?String(t.uid):'';jobFilter.value=t.job==null?'':String(t.job);minimum.value=t.min_level??0;maximum.value=t.max_level??255;name.value=t.q||''
 rewardMode.value=d.account_reward_mode;reason.value=d.reason;gold.value=r.gold||0;message.value=r.message??'GM rewards';mailTitle.value=r.mail_title??'';amounts.value={cera:0,cera_point:0,mileage:0,...r.currency_rewards}
 items.value=(r.items||[]).map((i:any)=>({...i,name:i.name||'#'+i.id}));template.value=d.reward.template_id?{id:d.reward.template_id,current_version:d.reward.template_version,name:'原计划礼包 #'+d.reward.template_id}:null
},{immediate:true})
onMounted(async()=>{if(props.scheduleDraft)return;try{const saved=JSON.parse(sessionStorage.getItem(storage)||'null');if(saved&&/^[a-f0-9]{32}$/.test(saved.id)){pendingId.value=saved.id;key.value=saved.key||'';uncertain.value=!!saved.uncertain;queryId.value=saved.id;await inspect(saved.id)}}catch(e){lookupError.value=uncertainMessage(e)}try{if(props.initialJob){if(uncertain.value&&pendingId.value!==props.initialJob){lookupError.value='已优先恢复结果待确认的任务；请先核对，再查看异常中心选择的任务 '+props.initialJob}else{await inspect(props.initialJob);draftVisible.value=false}emit('opened')}}catch(e){lookupError.value=uncertainMessage(e)}await list();if(!alive)return;timer=setInterval(()=>{if(!busy.value&&!document.hidden&&selected.value){busy.value=true;void inspect(selected.value.id,false).catch(e=>{lookupError.value=uncertainMessage(e)}).finally(()=>{busy.value=false})}},30000)})
onBeforeUnmount(()=>{alive=false;if(timer)clearInterval(timer)})
</script>
<template>
 <section class="reward-jobs">
  <section class="panel">
   <div class="section-title"><h2>{{scheduleDraft?'定时奖励内容与收件规则':'批量奖励任务'}}</h2><button @click="draftVisible=!draftVisible">{{draftVisible?'收起新任务':'创建新任务'}}</button></div>
   <p v-if="scheduleDraft" class="field-hint">此处只定义奖励和规则；计划到期时才冻结收件名单。点击底部按钮预览整个定时计划，不会立即发奖。</p>
   <p v-else class="field-hint">先固定名单和奖励，再确认启动。账号货币按执行时余额累加，物品与金币邮件逐角色投递；不会因关闭网页而丢失进度。</p>
   <form v-show="draftVisible" @submit.prevent="preview">
    <fieldset :disabled="busy||uncertain">
     <h3>1. 收件范围</h3>
     <label>目标模式<select v-model="mode" aria-label="目标模式"><option value="selected">勾选／导入指定角色</option><option value="accounts">指定／导入账号名单</option><option value="filtered">按条件筛选角色</option><option value="online">在线账号下的角色</option><option value="all">全服未删除角色</option></select></label>
     <template v-if="mode==='selected'"><CharacterPicker v-model="ids"/><label>角色编号名单<textarea v-model="ids" aria-label="角色编号名单" placeholder="例如 900001, 900003；支持换行粘贴" :aria-invalid="!!fieldErrors.ids"/></label><p v-if="fieldErrors.ids" class="submit-error" role="alert">{{fieldErrors.ids}}</p><label class="file-input">导入纯文本名单<input type="file" accept=".txt,.csv" aria-label="导入角色名单" @change="importIds"></label><p class="field-hint">仅在浏览器读取编号文件，不上传文件；重复编号会去重。</p></template>
     <template v-else-if="mode==='accounts'"><label>账号标识类型<select v-model="accountKind" aria-label="账号名单类型"><option value="uid">账号 UID</option><option value="name">账号名（精确匹配）</option></select></label><label>账号名单<textarea v-model="accountList" aria-label="账号名单" placeholder="每行一个，不含表头；也可用逗号分隔" :aria-invalid="!!fieldErrors.accounts"/></label><p v-if="fieldErrors.accounts" class="submit-error" role="alert">{{fieldErrors.accounts}}</p><label class="file-input">导入账号名单<input type="file" accept=".txt,.csv" aria-label="导入账号名单" @change="importAccounts"></label><p class="notice">选择这些账号下的所有未删除角色，不是只选一个角色。账号名区分大小写；纯数字账号名也请选择“账号名”。重复账号去重，货币按下方规则发放，邮件逐角色发放。</p><p class="field-hint">仅本地读取UTF-8无表头单列文件，不上传文件。定时计划预览会绑定账号UID，之后按该UID在触发时选择角色，不跟随同名新账号。</p></template>
     <div v-else-if="mode!=='all'" class="reward-grid"><label>账号 UID<input v-model="uid" aria-label="筛选账号UID" inputmode="numeric" placeholder="全部账号"></label><label>职业编号<input v-model="jobFilter" inputmode="numeric" placeholder="全部职业"></label><label>角色名称<input v-model="name" maxlength="80" placeholder="包含名称"></label><label>最低等级<input v-model.number="minimum" type="number" min="0" max="255"></label><label>最高等级<input v-model.number="maximum" type="number" min="0" max="255"></label></div>
     <p v-if="importNotice" class="notice" role="status">{{importNotice}}</p>
     <p v-if="fieldErrors.filters" class="submit-error" role="alert">{{fieldErrors.filters}}</p>
     <p v-if="mode==='online'" class="notice">选择在线账号下所有符合条件的角色，不代表这些角色同时在线。</p><p v-if="mode==='all'" class="notice">范围是全服有归属账号的未删除角色。不包含没有角色的账号。启动前需再次确认。</p>
     <h3>2. 奖励内容</h3>
     <div class="toolbar"><label>查找礼包模板<input v-model="templateQuery" aria-label="查找礼包模板" placeholder="名称或编号"></label><button type="button" @click="findTemplates">查询模板</button></div>
     <div v-if="templates.length" class="reward-results"><button v-for="g in templates" :key="g.id" type="button" :disabled="!g.enabled" @click="selectTemplate(g)">{{g.name}} · v{{g.current_version}}{{g.enabled?'':' · 已停用'}}</button></div>
     <div v-if="template" class="notice">来源 {{template.name}} v{{template.current_version}} · {{adjusted?'临时调整，不修改原模板':'按模板原内容发放'}}。<button v-if="!adjusted&&template.rewards" type="button" @click="adjustTemplate">临时调整本次奖励</button><button type="button" @click="template=null">解除模板绑定</button></div>
     <template v-if="!template||adjusted">
      <div class="reward-grid"><label v-for="(label,k) in currencyNames" :key="k">{{label}}<input v-model.number="amounts[k]" type="number" min="0" max="1000000000" :aria-label="'批量'+label"></label><label>每角色邮件金币<input v-model.number="gold" type="number" min="0" max="1000000000" aria-label="批量金币附件"></label></div>
      <div class="toolbar"><label>搜索物品<input v-model="query" aria-label="批量物品搜索" placeholder="物品名称或编号" @keydown.enter.prevent="findItems"></label><button type="button" @click="findItems">搜索物品</button></div>
      <div class="reward-results"><button v-for="item in found" :key="item.id" type="button" :disabled="item.sendable===false" @click="add(item)">＋ {{item.name}} #{{item.id}}</button></div>
      <ItemQueue :items="items" :busy="busy" prefix="batch" :errors="fieldErrors" @remove="items.splice($event,1)" @quantity="(n,q)=>items[n].quantity=q"/>
      <label>邮件标题（作为正文首行）<input v-model="mailTitle" maxlength="40" aria-label="批量邮件标题" :aria-invalid="!!fieldErrors['batch-title']"></label><p v-if="fieldErrors['batch-title']" class="submit-error" role="alert">{{fieldErrors['batch-title']}}</p>
      <label>邮件文字<input v-model="message" maxlength="60" aria-label="批量邮件文字"></label>
     </template>
     <p v-if="searchError" class="submit-error" role="alert">{{searchError}}</p><p v-if="fieldErrors.reward" class="submit-error" role="alert">{{fieldErrors.reward}}</p>
     <label>账号货币发放规则<select v-model="rewardMode" aria-label="账号货币规则"><option value="once_per_account">同账号只发一次（推荐）</option><option value="per_character">每个角色都发一次到所属账号</option></select></label>
     <p class="field-hint">该规则仅影响点券、代币券和积分；物品与邮件金币始终逐角色发放。</p>
     <label>发放原因<textarea v-model="reason" maxlength="200" aria-label="批量发放原因" :aria-invalid="!!fieldErrors.reason"/></label><p v-if="fieldErrors.reason" class="submit-error" role="alert">{{fieldErrors.reason}}</p>
     <button class="primary" type="submit">{{scheduleDraft?'预览定时奖励计划':'生成批量预览'}}</button>
    </fieldset>
   </form>
  </section>
  <section v-if="!scheduleDraft&&selected" class="panel" aria-label="任务预览与进度">
   <div class="section-title"><h2>{{labels[selected.status]||selected.status}}</h2><span class="pill">角色 {{selected.target_count}} ／ 账号 {{selected.account_count}}</span></div>
   <p>任务编号：<code>{{selected.id}}</code></p><p>原因：{{selected.reason}}</p>
   <p v-if="selected.pause_reason" class="notice">{{selected.pause_reason}}</p>
   <p v-if="!selected.worker_enabled" class="notice">执行器未启用；不能启动或继续发放。</p>
   <div class="reward-grid"><div v-for="(value,k) in selected.preview.currency_totals" :key="k">{{currencyNames[k]||k}}合计：<strong>{{value}}</strong></div><div>邮件金币合计：<strong>{{selected.preview.gold_total}}</strong></div></div>
   <p v-if="selected.preview.account_selection" class="notice">账号名单：{{selected.preview.account_selection.requested_accounts}} 个账号，已去除 {{selected.preview.account_selection.duplicates_removed}} 条重复输入；名单包含这些账号下的全部未删除角色。</p>
   <p v-if="selected.request.reward.template_id">来源礼包 #{{selected.request.reward.template_id}} / v{{selected.request.reward.template_version}} · {{selected.request.reward.template_overrides?'临时调整（原模板未修改）':'模板原内容'}}</p>
   <p>账号货币：{{selected.request.account_reward_mode==='once_per_account'?'同账号只发一次':'逐角色重复发到所属账号'}}</p>
   <ul><li v-for="(item,n) in selected.preview.rewards.items" :key="n">每角色 {{item.name||'#'+item.id}} #{{item.id}} × {{item.quantity}}</li></ul>
   <p v-if="selected.preview.mail_title" style="white-space:pre-wrap">邮件正文预览：
{{selected.preview.mail_text}}</p>
   <p class="field-hint">{{selected.preview.note}}</p>
   <div class="toolbar"><span v-for="(count,state) in selected.counts" :key="state" class="pill">{{labels[state]||state}} {{count}}</span></div>
   <template v-if="selected.status==='preview'">
    <p class="notice">这份预览只在生成后5分钟内有效；确认的是上面已固定的名单和奖励，而不是正在修改的草稿。</p>
    <label v-if="selected.request.targets.mode==='all'">输入“全服发放”确认<input v-model="confirmation" aria-label="全服确认" :disabled="busy||uncertain"></label>
    <label v-if="repeatNeeded" class="check-label"><input v-model="repeat" type="checkbox" :disabled="busy||uncertain">我确认同账号按角色数重复获得账号货币</label>
    <button class="primary" :disabled="busy||uncertain||!selected.worker_enabled||!selected.write_enabled" @click="start">确认启动该任务</button>
   </template>
   <div v-else class="toolbar">
    <button v-if="selected.status==='running'" :disabled="busy||uncertain" @click="control('pause')">暂停后续发放</button>
    <template v-if="['paused','needs_attention'].includes(selected.status)"><button :disabled="busy||uncertain||!selected.worker_enabled" @click="control('resume')">继续未执行目标</button><button :disabled="busy||uncertain" @click="control('reconcile')">核对中断目标</button><button :disabled="busy||uncertain||!selected.counts.failed" @click="control('retry-failed')">重新排队未提交目标</button></template>
    <button v-if="selected.status==='cancelled'&&(selected.counts.uncertain||selected.counts.executing)" :disabled="busy||uncertain" @click="control('reconcile')">只核对已取消任务的中断目标（不重发）</button>
    <button v-if="['running','paused','needs_attention'].includes(selected.status)" :disabled="busy||uncertain" @click="control('cancel')">取消剩余目标（不撤销已发）</button>
   </div>
   <p v-if="uncertain" class="submit-error" role="alert">启动结果待确认。只查询原任务，禁止重新创建或重复发放。刷新页面后仍会保留这个任务编号。</p>
   <p v-if="error" class="submit-error" role="alert">{{error}}</p><p v-if="notice" class="notice" role="status">{{notice}}</p>
   <div class="toolbar"><button :disabled="busy" @click="queryOriginal">刷新原任务（只读）</button><span class="field-hint">最近核对 {{checked||'尚未核对'}} · 可见页面每30秒查询</span></div>
   <div class="table-wrap"><table><thead><tr><th>角色／账号</th><th>执行状态</th><th>操作编号／详情</th></tr></thead><tbody><tr v-for="target in targets" :key="target.ordinal"><td>{{target.target.charac_name}} #{{target.charac_no}}<small class="cell-note">{{target.target.accountname}} #{{target.target_uid}}</small></td><td>{{labels[target.status]||target.status}}<small class="cell-note">尝试 {{target.attempts}} 次</small></td><td><code>{{target.operation_id}}</code><button v-if="target.status==='committed'" :disabled="busy" @click="emit('inspect',target.operation_id)">查看原操作结果</button><small v-if="target.error_message" class="cell-note">{{target.error_message}}</small></td></tr></tbody></table></div>
   <div class="pagination"><button :disabled="busy||!previous.length" @click="move(false)">上一页目标</button><span>从第 {{cursor+1}} 条开始</span><button :disabled="busy||next===null" @click="move(true)">下一页目标</button></div>
  </section>
  <p v-else-if="error" class="submit-error" role="alert">{{error}}</p>
  <p v-if="lookupError" class="submit-error" role="alert">{{lookupError}}，当前显示可能是旧快照，请刷新核对。</p>
  <section v-if="!scheduleDraft" class="panel">
   <div class="section-title"><h2>任务历史</h2><button :disabled="busy" @click="list">刷新任务列表</button></div>
   <form class="toolbar" @submit.prevent="queryOriginal"><label>按原任务编号恢复查看<input v-model="queryId" aria-label="查询任务编号" :disabled="uncertain" placeholder="32位任务编号"></label><button :disabled="busy">查询原任务</button></form>
   <div v-if="!jobs.length" class="empty">暂无任务</div>
   <div v-for="j in jobs" :key="j.id" class="job-row"><div><strong>{{j.reason}}</strong><small class="cell-note">{{j.id}} · {{labels[j.status]||j.status}} · {{j.target_count}}角色</small></div><button :disabled="busy||uncertain" @click="choose(j.id)">查看任务</button></div>
   <div class="pagination"><button :disabled="busy||page===1" @click="page--;list()">上一页任务</button><span>第 {{page}} 页</span><button :disabled="busy||!more" @click="page++;list()">下一页任务</button></div>
  </section>
 </section>
</template>
<style scoped>
.reward-jobs{display:grid;gap:20px}.reward-jobs fieldset{border:0;padding:0;margin:0;min-width:0;display:grid;gap:12px}.reward-jobs h3{margin:14px 0 0}.reward-jobs label{display:grid;gap:6px}.reward-jobs textarea{min-height:80px;width:100%;resize:vertical}.reward-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}.reward-results{display:flex;gap:8px;flex-wrap:wrap;max-height:220px;overflow:auto}.job-row{display:flex;gap:12px;justify-content:space-between;align-items:center;padding:14px 0;border-bottom:1px solid var(--border-color)}.reward-jobs code,.job-row small{overflow-wrap:anywhere;word-break:break-all}.reward-jobs .check-label{display:flex;align-items:center}.reward-jobs .check-label input{width:auto}.reward-jobs .toolbar label{flex:1}.file-input input{max-width:100%}
@media(max-width:600px){.reward-grid{grid-template-columns:1fr 1fr}.reward-jobs table,.reward-jobs tbody,.reward-jobs tr,.reward-jobs td{display:block;min-width:0;width:100%}.reward-jobs thead{display:none}.reward-jobs td{white-space:normal;border:0;padding:6px 0}.reward-jobs tr{padding:10px 0;border-bottom:1px solid var(--border-color)}.job-row{align-items:flex-start}.reward-jobs .toolbar{flex-wrap:wrap}}
.reward-jobs .toolbar label{flex:1 1 200px}.reward-jobs .toolbar label input{flex:0 0 auto}
</style>
