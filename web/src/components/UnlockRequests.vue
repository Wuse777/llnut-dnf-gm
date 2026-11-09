<script setup lang="ts">
import {ref,onMounted,onBeforeUnmount,computed,watch} from 'vue'
import UnlockItem from './UnlockItem.vue'
import {api,ApiError,uncertainMessage} from '../api'
import {useGmConfirmation} from '../stores/gm/confirmation'
const confirmationLease=useGmConfirmation()
import FieldError from './FieldError.vue'
const props=defineProps<{characNo:number,selectOnly?:boolean}>()
const emit=defineEmits<{reauth:[],expired:[],busy:[value:boolean],pending:[value:boolean],select:[value:any]}>()
const data=ref<any>(null),loading=ref(false),error=ref(''),reason=ref(''),reasonError=ref(''),selected=ref<number[]>([])
const tick=ref(Date.now());let loadedAt=Date.now(),timer:ReturnType<typeof setInterval>|undefined
const now=computed(()=>(data.value?.collected_at??tick.value/1000)+(tick.value-loadedAt)/1000)
function eligible(i:any){return i.state===2&&!i.expired&&i.due_at>now.value}
function remaining(i:any){const n=Math.max(0,Math.ceil(i.due_at-now.value));return n?Math.floor(n/3600)+'小时 '+Math.floor(n%3600/60)+'分 '+n%60+'秒':'已到期，待游戏处理'}
function choose(){error.value='';const chosen=data.value.items.filter((i:any)=>selected.value.includes(i.lock_key));if(!chosen.length||chosen.some((i:any)=>!eligible(i))){error.value='选中申请已到期或不可处理，请刷新后重新选择。';return}emit('select',{uid:data.value.uid,charac_no:props.characNo,lock_keys:[...selected.value],requests:chosen})}
const preview=ref<any>(null),result=ref<any>(null),uncertain=ref(false),key=ref('')
function date(n:number){return n?new Date(n*1000).toLocaleString('zh-CN',{hour12:false}):'未记录'}
function busy(v:boolean){loading.value=v;emit('busy',v)}
function fail(e:unknown){error.value=uncertainMessage(e);if(e instanceof ApiError&&e.status===401)emit('expired');if(e instanceof ApiError&&e.status===403&&e.message.includes('重新认证'))emit('reauth')}
async function load(){if(loading.value)return;busy(true);error.value='';data.value=null;selected.value=[];try{data.value=await api('/characters/'+props.characNo+'/unlock-requests');selected.value=[];loadedAt=Date.now();tick.value=loadedAt}catch(e){fail(e)}finally{busy(false)}}
async function makePreview(){
 if(loading.value)return
 error.value='';reasonError.value=''
 if(!reason.value.trim()){reasonError.value='请填写提前解锁原因。';return}
 if(!selected.value.length){error.value='请先选择待处理申请。';return}
 if(data.value.items.some((i:any)=>selected.value.includes(i.lock_key)&&!eligible(i))){error.value='选中申请已到期，请刷新后重新选择。';return}
 if(!confirmationLease.acquire('domain-unlockrequests')){error.value='请先完成或关闭当前确认面板。';return}
 busy(true)
 try{preview.value=await api('/operations/preview','POST',{action:'equipment-unlock',uid:data.value.uid,charac_no:props.characNo,lock_keys:[...selected.value],reason:reason.value.trim()});emit('pending',true);key.value=crypto.randomUUID();result.value=null;uncertain.value=false}catch(e){fail(e)}finally{busy(false);if(!preview.value||result.value)confirmationLease.release('domain-unlockrequests')}
}
async function confirm(){
 if(loading.value||uncertain.value||result.value)return
 if(!confirmationLease.acquire('domain-unlockrequests')){error.value='请先完成或关闭当前确认面板。';return}
 busy(true);error.value='';uncertain.value=true
 try{result.value=await api('/operations/'+preview.value.operation_id+'/confirm','POST',{idempotency_key:key.value});uncertain.value=false}catch(e){if(e instanceof ApiError&&[401,403,404,409,422].includes(e.status))uncertain.value=false;fail(e)}finally{busy(false)}
}
async function query(){if(loading.value)return;busy(true);error.value='';try{const d=await api('/operations/'+preview.value.operation_id);if(d.status==='committed'){result.value=d.result;uncertain.value=false}else error.value='尚未查到提交结果。请保留原编号，不要新建重复操作。'}catch(e){fail(e)}finally{busy(false)}}
async function reset(){emit('pending',false);preview.value=null;result.value=null;await load()}
onMounted(()=>{void load();timer=setInterval(()=>{if(!document.hidden)tick.value=Date.now()},1000)})
onBeforeUnmount(()=>{if(timer)clearInterval(timer)})
watch(()=>!!preview.value&&!result.value,active=>{if(active)confirmationLease.acquire('domain-unlockrequests');else confirmationLease.release('domain-unlockrequests')})
onBeforeUnmount(()=>confirmationLease.release('domain-unlockrequests'))
</script>
<template>
 <div class="unlock-requests" data-testid="unlock-requests">
  <div class="section-title"><h3>装备锁定 / 解锁申请</h3><button :disabled="loading||!!preview" @click="load">刷新申请</button></div>
  <p class="field-hint">仅处理明确选择的待解锁申请，不直接删除装备锁。必须完全退出账号，处理期间不要登录。设为到期后，下次登录加载角色由游戏执行；不承诺当前客户端即时解锁。</p>
  <p v-if="error" class="submit-error" role="alert">{{error}}</p>
  <p v-if="loading" role="status">正在处理…</p>
  <template v-if="data&&!preview">
   <p>{{data.login_status===0?'账号离线':data.login_status===1?'账号在线：仅可查看，请先完全退出账号':'登录状态未知：禁止修改'}} · 原生等待 {{data.wait_seconds/3600}} 小时 · 采集 {{date(data.collected_at)}}</p>
   <p v-if="data.state!=='ok'" class="submit-error">{{data.message}}</p>
   <p class="field-hint">{{data.note}}</p>
   <div v-if="data.items.length" class="button-row"><button type="button" :disabled="loading||!data.write_enabled||data.login_status!==0||!!data.delete_flag" @click="selected=data.items.filter(eligible).map((i:any)=>i.lock_key)">全选本角色待处理申请</button><button type="button" :disabled="loading||!selected.length" @click="selected=[]">清除选择</button></div>
   <div v-if="data.items.length" class="table-wrap"><table><thead><tr><th>选择</th><th>锁定编号</th><th>物品 / 位置</th><th>状态</th><th>申请 / 到期时间</th></tr></thead><tbody><tr v-for="i in data.items" :key="i.lock_key"><td><input v-model="selected" type="checkbox" :value="i.lock_key" :aria-label="'选择解锁申请 '+i.lock_key" :disabled="loading||!data.write_enabled||data.login_status!==0||!!data.delete_flag||!eligible(i)"></td><td>#{{i.lock_key}}</td><td><UnlockItem :request="i"/></td><td>{{i.state===1?'已锁定（尚未申请）':!eligible(i)?'已到期，待游戏处理':'待解锁申请'}}<small v-if="i.managed_operation" class="cell-note">后台已设到期 · {{i.managed_operation}}</small></td><td>{{i.state===2?date(i.requested_at):'—'}}<small class="cell-note">{{i.state===2?date(i.due_at):'未申请解锁'}}</small><small v-if="i.state===2" class="cell-note">{{remaining(i)}}</small></td></tr></tbody></table></div>
   <p v-else class="empty">没有已保存的锁定记录或解锁申请。</p>
   <p v-if="!data.write_enabled" class="warning">提前解锁未启用或存档格式不支持。</p>
   <button v-if="selectOnly" class="primary" :disabled="loading||!selected.length||data.login_status!==0||!!data.delete_flag||!data.write_enabled" @click="choose">加入批量处理清单（{{selected.length}}项）</button>
   <template v-else>
   <label for="unlock-reason">提前解锁原因 <i class="required-tag">必填</i></label><input id="unlock-reason" v-model="reason" maxlength="200" :disabled="loading" :aria-invalid="!!reasonError" aria-describedby="unlock-reason-error" @input="reasonError=''">
   <FieldError id="unlock-reason-error" :message="reasonError"/>
   <button class="primary" :disabled="loading||!selected.length||data.login_status!==0||!!data.delete_flag||!data.write_enabled" @click="makePreview">预览提前解锁（{{selected.length}}项）</button>
   </template>
  </template>
  <template v-if="preview">
   <h3>提前解锁确认 · {{preview.preview.target.accountname}} / {{preview.preview.target.character.charac_name}}</h3>
   <p>锁定编号：{{preview.preview.requests.map((i:any)=>'#'+i.lock_key).join('、')}} · 原因：{{preview.preview.reason}}</p>
   <div class="unlock-preview-items"><UnlockItem v-for="i in preview.preview.requests" :key="i.lock_key" :request="i"/></div><p class="warning">{{preview.preview.note}}。仅此选择，不改变全服等待时间；预览5分钟有效，存档或登录状态变化将被拒绝。</p>
   <p class="mono operation-number">操作编号 {{preview.operation_id}}</p>
   <p v-if="uncertain" class="warning" role="status">结果待确认。不要重复操作；请按原编号查询，关闭前复制编号。</p>
   <p v-if="result" class="submit-success" role="status">选中申请已设为到期。请重新登录加载角色；本后台未验证客户端最终解锁效果。</p>
   <div class="toolbar"><button v-if="!uncertain" :disabled="loading" @click="reset">{{result?'刷新处理后的申请':'返回修改'}}</button><button :disabled="loading" @click="query">按原编号查询结果</button><button v-if="!result" class="primary" :disabled="loading||uncertain||!preview.write_enabled" @click="confirm">确认提前处理一次</button></div>
  </template>
 </div>
</template>
