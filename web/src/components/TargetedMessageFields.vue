<script setup lang="ts">
import {computed,onMounted,onBeforeUnmount,ref,watch} from 'vue'
import {api,ApiError,uncertainMessage} from '../api'
const props=defineProps<{account?:any,busy?:boolean,characNo?:number|null,error?:string}>()
const emit=defineEmits<{'update:characNo':[value:number|null],ready:[value:boolean],'select-player':[],reauth:[],expired:[]}>()
const capability=ref<any>(null),statusBusy=ref(false),statusError=ref(''),roles=ref<any[]>([]),rolesBusy=ref(false),rolesError=ref(''),page=ref(1)
const usable=computed(()=>capability.value?.implemented===true&&capability.value?.enabled===true&&capability.value?.ready===true&&capability.value?.bridge_state==='ready')
const statusLabel=computed(()=>statusBusy.value?'正在核验能力':statusError.value?'能力状态读取失败':!capability.value?'能力状态未知':!capability.value.implemented?'当前版本未实现':!capability.value.enabled?'能力已停用':capability.value.bridge_state!=='ready'?'游戏桥接未就绪':!capability.value.ready?'能力尚未就绪':'已就绪，可生成预览')
let alive=true,roleEpoch=0,statusEpoch=0
function auth(e:unknown){if(e instanceof ApiError&&e.status===401)emit('expired');if(e instanceof ApiError&&e.status===403&&e.message.includes('重新认证'))emit('reauth')}
async function loadStatus(){
 const epoch=++statusEpoch;statusBusy.value=true;statusError.value='';emit('ready',false)
 try{const r=await api('/native-controls/status');if(alive&&epoch===statusEpoch){capability.value=r.private_message??null;emit('ready',usable.value)}}
 catch(e){if(alive&&epoch===statusEpoch){capability.value=null;statusError.value=uncertainMessage(e);auth(e)}}finally{if(alive&&epoch===statusEpoch)statusBusy.value=false}
}
async function loadRoles(){
 const epoch=++roleEpoch;roles.value=[];rolesError.value='';emit('update:characNo',null)
 if(!props.account?.uid){rolesBusy.value=false;return}
 rolesBusy.value=true
 try{const r=await api('/characters?uid='+props.account.uid+'&page='+page.value);if(alive&&epoch===roleEpoch)roles.value=Array.isArray(r.items)?r.items:[]}
 catch(e){if(alive&&epoch===roleEpoch){rolesError.value=uncertainMessage(e);auth(e)}}finally{if(alive&&epoch===roleEpoch)rolesBusy.value=false}
}
function choose(e:Event){const id=Number((e.target as HTMLSelectElement).value);emit('update:characNo',roles.value.some(r=>r.charac_no===id&&!r.delete_flag)?id:null)}
watch(()=>props.account?.uid,()=>{page.value=1;void loadRoles()},{immediate:true})
onMounted(()=>void loadStatus())
onBeforeUnmount(()=>{alive=false;roleEpoch++;statusEpoch++;emit('ready',false)})
</script>
<template>
 <div class="targeted-message-fields">
  <section class="targeted-readiness" aria-label="定向消息能力状态">
   <div class="section-title"><strong>定向系统消息</strong><span class="status-badge" :class="usable?'success':'neutral'" role="status">{{statusLabel}}</span></div>
   <p class="field-hint">{{capability?.note||'只向所选角色请求显示系统消息。发送记录不能证明客户端已显示或玩家已阅读。'}}</p>
   <p v-if="statusError" class="submit-error" role="alert">{{statusError}}</p>
   <button type="button" :disabled="busy||statusBusy" @click="loadStatus">重新核验消息能力</button>
  </section>
  <div class="native-target">
   <div class="button-row"><strong v-if="account">{{account.accountname}} · UID {{account.uid}}</strong><span v-else>尚未选择账号</span><button type="button" :disabled="busy" @click="emit('select-player')">{{account?'更换账号':'选择账号'}}</button></div>
   <template v-if="account"><label for="native-message-character">收信角色 <i class="required-tag">必填</i></label><select id="native-message-character" :value="characNo??''" :disabled="busy||rolesBusy" :aria-invalid="!!error" @change="choose"><option value="">请选择当前账号下的角色</option><option v-for="role in roles" :key="role.charac_no" :value="role.charac_no" :disabled="!!role.delete_flag">{{role.charac_name}} · #{{role.charac_no}} · Lv.{{role.lev}}{{role.delete_flag?' · 已删除':''}}</option></select><p v-if="rolesBusy" role="status">正在读取当前账号的角色…</p><p v-if="rolesError" class="submit-error" role="alert">{{rolesError}} <button type="button" :disabled="busy||rolesBusy" @click="loadRoles">重试读取角色</button></p><div class="pagination"><button type="button" :disabled="busy||rolesBusy||page<=1" @click="page--;loadRoles()">上一页收信角色</button><small>第 {{page}} 页</small><button type="button" :disabled="busy||rolesBusy||roles.length<50" @click="page++;loadRoles()">下一页收信角色</button></div></template>
   <p v-if="error" class="submit-error" role="alert">{{error}}</p><p class="field-hint">目标与账号归属会在预览和确认时重新核对。离线或切换角色可能无法显示，页面不会自动重发。</p>
  </div>
 </div>
</template>
<style scoped>
.targeted-message-fields{display:grid;gap:12px}.targeted-readiness,.native-target{padding:14px;border:1px solid var(--border-color);border-radius:12px}.targeted-readiness .section-title{margin-bottom:6px;flex-wrap:wrap;gap:8px}.targeted-readiness strong{font-size:13px}.targeted-readiness button{font-size:12px}.native-target label{display:block;margin:16px 0 6px}.targeted-message-fields .pagination{margin-bottom:0}.targeted-message-fields .pagination button{font-size:11px;padding:7px 10px}.targeted-readiness .status-badge{white-space:normal}
</style>
