<script setup lang="ts">
import {ref,onMounted,onBeforeUnmount,computed,watch} from 'vue'
import {api,ApiError,uncertainMessage} from '../api'
import {useGmConfirmation} from '../stores/gm/confirmation'
const confirmationLease=useGmConfirmation()
import UnlockRequests from './UnlockRequests.vue'
import UnlockItem from './UnlockItem.vue'
const emit=defineEmits<{reauth:[],inspect:[id:string]}>()
const query=ref(''),uid=ref(''),state=ref('pending'),after=ref(0),next=ref<number|null>(null),previous=ref<number[]>([])
const rows=ref<any[]>([]),note=ref(''),active=ref<any>(null),basket=ref<any[]>([]),reason=ref(''),reasonError=ref('')
const loading=ref(false),busy=ref(false),error=ref(''),lookupError=ref(''),preview=ref<any>(null),result=ref<any>(null),uncertain=ref(false),operation=ref(''),key=ref(''),lookup=ref('')
const locked=computed(()=>busy.value||!!preview.value||uncertain.value)
const storage='dnf-gm.unlock-batch-pending';let generation=0,alive=true,timer:ReturnType<typeof setInterval>|undefined
function fail(e:unknown){error.value=uncertainMessage(e);if(e instanceof ApiError&&e.status===403&&e.message.includes('重新认证'))emit('reauth')}
function save(){sessionStorage.setItem(storage,JSON.stringify({id:operation.value,uncertain:uncertain.value}))}
async function load(reset=false){
 if(reset){after.value=0;previous.value=[]}
 if(uid.value&&(!/^\d+$/.test(uid.value)||Number(uid.value)>2147483647)){lookupError.value='账号UID须为有效整数。';return}
 const ticket=++generation;loading.value=true;lookupError.value=''
 try{const d=await api('/unlock-requests?q='+encodeURIComponent(query.value)+'&uid='+Number(uid.value||0)+'&state='+state.value+'&after='+after.value);if(alive&&ticket===generation){rows.value=d.items;next.value=d.next_after;note.value=d.note}}
 catch(e){if(ticket===generation)lookupError.value=uncertainMessage(e)}finally{if(ticket===generation)loading.value=false}
}
function add(value:any){if(locked.value)return;error.value='';const i=basket.value.findIndex(t=>t.charac_no===value.charac_no);if(i<0&&basket.value.length>=20){error.value='每次原子处理最多20个角色，请分批提交。';return}const t={...value,accountname:active.value.accountname,charac_name:active.value.charac_name};if(i>=0)basket.value.splice(i,1,t);else basket.value.push(t);active.value=null}
async function makePreview(){
 if(locked.value)return;reasonError.value='';error.value=''
 if(!reason.value.trim()){reasonError.value='请填写本批次提前解锁原因。';return}
 if(!basket.value.length){error.value='请先选择角色申请并加入处理清单。';return}
 if(!confirmationLease.acquire('domain-unlockcenter')){error.value='请先完成或关闭当前确认面板。';return}
 busy.value=true
 try{const p=await api('/unlock-batches/preview','POST',{reason:reason.value.trim(),targets:basket.value.map(t=>({uid:t.uid,charac_no:t.charac_no,lock_keys:t.lock_keys}))});preview.value=p;operation.value=p.operation_id;key.value=crypto.randomUUID();result.value=null;uncertain.value=false;save()}
 catch(e){fail(e)}finally{busy.value=false;if(!preview.value||result.value)confirmationLease.release('domain-unlockcenter')}
}
async function confirm(){
 if(busy.value||uncertain.value||result.value||!preview.value?.write_enabled)return
 if(!confirmationLease.acquire('domain-unlockcenter')){error.value='请先完成或关闭当前确认面板。';return}
 busy.value=true;error.value='';uncertain.value=true
 try{save()}catch{uncertain.value=false;busy.value=false;error.value='无法保存待确认操作编号，本次未发送，请检查浏览器会话存储。';return}
 try{result.value=await api('/operations/'+operation.value+'/confirm','POST',{idempotency_key:key.value});uncertain.value=false;sessionStorage.removeItem(storage)}
 catch(e){if(e instanceof ApiError&&[401,403,404,409,422].includes(e.status)){uncertain.value=false;save()}fail(e)}finally{busy.value=false}
}
async function inspect(id=operation.value,knownUnsubmitted=false){
 if(busy.value||!id)return
 if(!/^[a-f0-9]{32}$/.test(id)){error.value='操作编号须为32位十六进制字符。';return}
 const localPreview=preview.value,canKeep=operation.value===id&&!!key.value&&!uncertain.value&&!result.value
 busy.value=true;error.value=''
 try{const d=await api('/operations/'+id);if(d.action!=='unlock-batch')throw new Error('该编号不是批量解锁操作。');operation.value=id;preview.value={operation_id:id,preview:d.preview,expires_at:d.expires_at,write_enabled:false};if(d.status==='committed'){result.value=d.result;uncertain.value=false;sessionStorage.removeItem(storage)}else if(canKeep){preview.value=localPreview;uncertain.value=false;error.value='此预览尚未提交，可确认一次或返回重选。'}else if(knownUnsubmitted){uncertain.value=false;error.value='恢复了尚未提交的预览，请放弃此预览并重选。'}else{uncertain.value=true;save();error.value='尚未确认提交成功；只查询原编号，不自动重发。'}}
 catch(e){fail(e)}finally{busy.value=false;if(!preview.value||result.value)confirmationLease.release('domain-unlockcenter')}
}
function reset(){if(busy.value||uncertain.value)return;preview.value=null;result.value=null;operation.value='';sessionStorage.removeItem(storage);basket.value=[];active.value=null;void load(true)}
function move(forward:boolean){if(forward){if(next.value===null)return;previous.value.push(after.value);after.value=next.value}else after.value=previous.value.pop()??0;void load()}
onMounted(async()=>{try{const saved=JSON.parse(sessionStorage.getItem(storage)||'null');if(saved&&/^[a-f0-9]{32}$/.test(saved.id)){operation.value=saved.id;uncertain.value=true;await inspect(saved.id,saved.uncertain===false)}}catch(e){fail(e)}await load();timer=setInterval(()=>{if(uncertain.value&&!document.hidden&&!busy.value)void inspect()},5000)})
onBeforeUnmount(()=>{alive=false;generation++;if(timer)clearInterval(timer)})
watch(()=>!!preview.value&&!result.value,active=>{if(active)confirmationLease.acquire('domain-unlockcenter');else confirmationLease.release('domain-unlockcenter')})
onBeforeUnmount(()=>confirmationLease.release('domain-unlockcenter'))
</script>
<template><section class="unlock-center">
 <section class="panel"><div class="section-title"><h2>装备解锁申请中心</h2><button :disabled="loading" @click="load()">刷新角色申请</button></div>
  <p class="field-hint">按账号或角色查找已保存的锁定记录；选择明确申请后统一预览，一批最多20个角色，同一事务全部处理或全部回滚。不改变全服等待时长，不删除装备锁。</p>
  <form class="toolbar" @submit.prevent="load(true)"><input v-model="query" aria-label="解锁角色搜索" placeholder="账号名、角色名、UID或角色编号" maxlength="80"><input v-model="uid" aria-label="解锁账号UID" placeholder="限定账号UID" inputmode="numeric"><select v-model="state" aria-label="解锁状态筛选"><option value="pending">待解锁申请</option><option value="expired">已到期待游戏处理</option><option value="all">全部锁定存档</option><option value="unsupported">格式异常</option></select><button :disabled="loading">查询申请角色</button></form>
  <p v-if="lookupError" class="submit-error" role="alert">{{lookupError}}</p><p v-if="loading" role="status">正在读取保存的申请…</p>
  <div v-if="rows.length" class="unlock-role-list"><article v-for="r in rows" :key="r.charac_no"><div><b>{{r.charac_name}} #{{r.charac_no}}</b><small class="cell-note">{{r.accountname??'账号缺失'}} / UID {{r.uid}} · {{r.login_status===0?'离线':r.login_status===1?'在线':'状态未知'}}{{r.delete_flag?' · 已删除':''}}</small><p v-if="r.state==='ok'">待处理 {{r.pending}} · 已到期 {{r.expired}} · 尚未申请 {{r.locked}}</p><p v-else class="submit-error">{{r.message}}</p></div><button :disabled="locked" @click="active=r">查看并选择申请</button></article></div>
  <p v-else-if="!loading&&!lookupError" class="empty">本页扫描没有符合条件的角色；如有下一页可继续，或选择全部状态。</p><p class="field-hint">{{note}}</p>
  <div class="pagination"><button :disabled="loading||!previous.length" @click="move(false)">上一页申请角色</button><span>第 {{previous.length+1}} 页 · 每次最多扫描25个角色</span><button :disabled="loading||next===null" @click="move(true)">下一页申请角色</button></div>
 </section>
 <section v-if="active&&!locked" class="panel"><div class="section-title"><h2>{{active.charac_name}}的申请</h2><button @click="active=null">收起角色申请</button></div><UnlockRequests :key="active.charac_no" :charac-no="active.charac_no" select-only @select="add" @reauth="emit('reauth')"/></section>
 <section class="panel">
  <h2>本次处理清单 · {{basket.length}} 个角色</h2><p class="field-hint">同一角色再次加入会替换该角色已选申请，不重复追加。清单可跨查询页保留，确认前仍会重新核验离线、身份和存档。</p>
  <template v-if="!preview"><article v-for="t in basket" :key="t.charac_no" class="unlock-basket-row"><div><b>{{t.charac_name}} / #{{t.charac_no}}</b><p>{{t.accountname}} / UID {{t.uid}} · 申请 {{t.lock_keys.join('、')}}</p></div><button :disabled="locked" @click="basket=basket.filter(x=>x.charac_no!==t.charac_no)">移除此角色</button></article>
   <label for="unlock-batch-reason">批量提前解锁原因 <i class="required-tag">必填</i></label><input id="unlock-batch-reason" v-model="reason" maxlength="200" :disabled="locked" :aria-invalid="!!reasonError" aria-describedby="unlock-batch-reason-error" @input="reasonError=''">
   <p v-if="reasonError" id="unlock-batch-reason-error" class="submit-error" role="alert">{{reasonError}}</p><button class="primary" :disabled="locked" @click="makePreview">生成批量解锁预览</button>
  </template>
  <template v-else><p>{{preview.preview.role_count}} 个角色 / {{preview.preview.request_count}} 条申请 · 原因：{{preview.preview.reason}}</p>
   <article v-for="t in preview.preview.targets" :key="t.target.character.charac_no" class="unlock-preview-target"><h3>{{t.target.accountname}} / {{t.target.character.charac_name}} #{{t.target.character.charac_no}}</h3><div v-for="i in t.requests" :key="i.lock_key"><b>申请 #{{i.lock_key}}</b><UnlockItem :request="i"/></div></article>
   <p class="warning">{{preview.preview.note}}。任一角色上线、归属或存档变化，本批次全部拒绝；没有部分解锁成功。</p><p class="mono operation-number">{{operation}}</p>
   <p v-if="uncertain" class="warning" role="status">结果待确认，已保存原编号，只读自动查询中。禁止重新提交。</p>
   <p v-if="result" class="submit-success" role="status">本批次数据库已提交：{{result.targets?.length}}个角色申请设为到期。不是游戏已解锁。</p>
   <div class="button-row"><button :disabled="busy||uncertain" @click="reset">{{result?'开始下一批':'放弃此预览并重选'}}</button><button :disabled="busy" @click="inspect()">查询原批次结果</button><button v-if="!result" class="primary" :disabled="busy||uncertain||!preview.write_enabled" @click="confirm">确认整批提前处理一次</button></div>
  </template>
  <p v-if="error" class="submit-error" role="alert">{{error}}</p>
  <details><summary>查询历史批次编号</summary><div class="toolbar"><input v-model="lookup" aria-label="历史解锁操作编号" placeholder="32位操作编号"><button :disabled="busy||uncertain" @click="inspect(lookup.trim())">查询历史解锁批次</button></div></details>
 </section>
</section></template>
