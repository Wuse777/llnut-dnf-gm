<script setup lang="ts">
import {computed,onMounted,onBeforeUnmount,ref} from 'vue'
import {api,ApiError,uncertainMessage} from '../api'
import {nativeNames,nativeStates,nativeReasons} from '../nativeStatus'
import TargetedMessageFields from './TargetedMessageFields.vue'
const props=defineProps<{account?:any}>()
const emit=defineEmits(['reauth','expired','select-player'])
const action=ref(props.account?.uid?'native-kick':'native-notice'),message=ref(''),reason=ref(''),error=ref(''),fields=ref<Record<string,string>>({})
const detail=ref<any>(null),history=ref<any[]>([]),page=ref(1),lookup=ref(''),busy=ref(false),attempted=ref(false),ack=ref(false),key=ref('')
const historyBusy=ref(false)
const messageCharacter=ref<number|null>(null),messageReady=ref(false)
let historyEpoch=0
const storage='dnfgm-native-operation',bytes=computed(()=>new TextEncoder().encode(message.value).length)
const pending=computed(()=>attempted.value&&detail.value?.status==='preview'||detail.value?.status==='dispatching')
const indeterminate=computed(()=>pending.value||detail.value?.status==='uncertain')
let alive=true,timer:ReturnType<typeof setInterval>|undefined
function fail(e:unknown){error.value=uncertainMessage(e);if(e instanceof ApiError&&e.status===403&&e.message.includes('重新认证'))emit('reauth');if(e instanceof ApiError&&e.status===401)emit('expired')}
function remember(id:string){sessionStorage.setItem(storage,id)}
async function historyLoad(){
 const epoch=++historyEpoch;historyBusy.value=true
 try{const r=await api('/native-controls?page='+page.value);if(alive&&epoch===historyEpoch)history.value=r.items}
 catch(e){if(alive&&epoch===historyEpoch)fail(e)}finally{if(alive&&epoch===historyEpoch)historyBusy.value=false}
}
async function inspect(id=detail.value?.operation_id){
 if(busy.value||!id)return
 if(!/^[a-f0-9]{32}$/.test(id)){error.value='请输入32位操作编号';return}
 const freshPreview=id===detail.value?.operation_id&&!attempted.value&&!!key.value
 busy.value=true;error.value=''
 try{const r=await api('/native-controls/'+id);if(!alive)return;detail.value=r;attempted.value=!freshPreview;history.value=history.value.map(row=>row.operation_id===id?{...row,...r}:row);remember(id)}catch(e){if(alive)fail(e)}finally{if(alive)busy.value=false}
}
async function prepare(){
 if(busy.value||detail.value)return
 error.value='';fields.value={}
 if(!reason.value.trim())fields.value.reason='请填写操作原因'
 if(action.value==='native-notice'||action.value==='native-message'){
  const name=action.value==='native-notice'?'公告':'消息'
  if(!message.value.trim())fields.value.message='请填写'+name+'内容'
  else if(/\p{C}/u.test(message.value))fields.value.message=name+'须为单行文字，不能包含换行或控制字符'
  else if(bytes.value>254)fields.value.message=name+'最多254个UTF-8字节，请缩短内容'
 }
 if(action.value!=='native-notice'&&!props.account?.uid)fields.value.target='请先在账号与角色页面选择目标账号'
 if(action.value==='native-message'){
  if(!messageCharacter.value)fields.value.target='请选择当前账号下的收信角色'
  if(!messageReady.value)fields.value.readiness='定向消息能力未就绪，请核验能力状态'
 }
 if(Object.keys(fields.value).length)return
 busy.value=true
 try{
  const r=await api('/native-controls/preview','POST',{action:action.value,uid:action.value==='native-notice'?null:props.account.uid,...(action.value==='native-message'?{charac_no:messageCharacter.value}:{}),message:['native-notice','native-message'].includes(action.value)?message.value:'',reason:reason.value.trim()})
  if(!alive)return
  remember(r.operation_id);key.value=crypto.randomUUID();detail.value=r;attempted.value=false;ack.value=false;await historyLoad()
 }catch(e){if(alive)fail(e)}finally{if(alive)busy.value=false}
}
async function confirm(){
 if(busy.value||attempted.value||!detail.value||detail.value.status!=='preview'||!key.value)return
 if(detail.value.preview.action==='native-notice'&&!ack.value){error.value='请确认这是全服广播，不是单人私信';return}
 busy.value=true;error.value=''
 try{
  remember(detail.value.operation_id);attempted.value=true
  const r=await api('/native-controls/'+detail.value.operation_id+'/confirm','POST',{idempotency_key:key.value})
  if(alive){detail.value=r;ack.value=false;await historyLoad()}
 }catch(e){if(alive){fail(e);if(e instanceof ApiError&&e.status===403&&e.message.includes('重新认证'))attempted.value=false}}
 finally{if(alive)busy.value=false}
}
async function cancel(){
 if(busy.value||detail.value?.status!=='preview')return
 busy.value=true;error.value=''
 try{const r=await api('/native-controls/'+detail.value.operation_id+'/cancel-preview','POST');if(alive){detail.value=r;attempted.value=true;ack.value=false;await historyLoad()}}catch(e){if(alive)fail(e)}finally{if(alive)busy.value=false}
}
function reset(){
 if(busy.value||detail.value?.status==='preview'||indeterminate.value&&!ack.value)return
 try{sessionStorage.removeItem(storage)}catch(e){fail(e);return}
 detail.value=null;attempted.value=false;ack.value=false;key.value='';error.value=''
}
onMounted(async()=>{
 try{const id=sessionStorage.getItem(storage);if(id&&/^[a-f0-9]{32}$/.test(id))await inspect(id)}catch(e){fail(e)}
 if(!alive)return
 await historyLoad();if(!alive)return
 timer=setInterval(()=>{if(!document.hidden&&pending.value&&!busy.value)void inspect()},5000)
})
onBeforeUnmount(()=>{alive=false;if(timer)clearInterval(timer)})
</script>
<template><section class="panel native-controls"><div class="section-title"><div><h2>游戏内控制</h2><p class="muted">公告、定向系统消息、账号踢下线与封禁联动 · 每次操作先预览</p></div></div>
 <p class="warning">发送记录不是游戏回执。全服公告会广播到当前monitor管理的游戏服务器；定向系统消息需先核验桥接能力。封禁和踢人分别记录结果。</p>
 <form v-if="!detail" @submit.prevent="prepare" class="native-form">
  <label for="native-action">操作类型</label><select id="native-action" v-model="action" :disabled="busy"><option v-for="(name,id) in nativeNames" :key="id" :value="id">{{name}}</option></select>
  <TargetedMessageFields v-if="action==='native-message'" :account="account" :busy="busy" v-model:charac-no="messageCharacter" :error="fields.target" @ready="messageReady=$event" @select-player="emit('select-player')" @reauth="emit('reauth')" @expired="emit('expired')"/>
  <template v-if="action==='native-notice'||action==='native-message'"><label for="native-message">{{action==='native-notice'?'公告':'定向消息'}}内容 <i class="required-tag">必填</i></label><textarea id="native-message" v-model="message" rows="3" :disabled="busy" :aria-invalid="!!fields.message" aria-describedby="native-message-error" @input="fields.message=''"/><small>{{bytes}} / 254 UTF-8字节 · 单行文字，中文通常占多个字节，不会自动截断</small><p v-if="fields.message" id="native-message-error" role="alert" class="submit-error">{{fields.message}}</p></template>
  <div v-else class="native-target"><strong v-if="account">{{account.accountname}} · UID {{account.uid}}</strong><span v-else>尚未选择账号</span><button type="button" :disabled="busy" @click="emit('select-player')">{{account?'更换账号':'选择账号'}}</button><p v-if="fields.target" role="alert" class="submit-error">{{fields.target}}</p><p class="field-hint">操作作用于账号当前会话，不指定某个角色。请核对UID，不以登录表状态保证玩家在线。</p></div>
  <label for="native-reason">操作原因 <i class="required-tag">必填</i></label><input id="native-reason" v-model="reason" maxlength="200" :disabled="busy" :aria-invalid="!!fields.reason" aria-describedby="native-reason-error" @input="fields.reason=''"/><p v-if="fields.reason" id="native-reason-error" role="alert" class="submit-error">{{fields.reason}}</p>
  <p v-if="fields.readiness" class="submit-error" role="alert">{{fields.readiness}}</p><button type="submit" class="primary" :disabled="busy||action==='native-message'&&!messageReady">生成控制预览</button>
 </form>
 <section v-else class="native-preview"><h3>{{nativeNames[detail.preview.action]}}</h3><p><b>{{detail.preview.target.accountname}}</b><span v-if="detail.preview.target.uid"> · UID {{detail.preview.target.uid}}</span><span v-if="detail.preview.target.charac_no"> · {{detail.preview.target.charac_name||'角色'}} #{{detail.preview.target.charac_no}}</span></p><blockquote v-if="detail.preview.message">{{detail.preview.message}}</blockquote><p>原因：{{detail.preview.reason}}</p><p v-if="detail.preview.action==='native-message'" class="field-hint">仅向以上账号的指定角色请求显示系统消息。sent 只表示服务器调用，不证明客户端已显示或玩家已阅读。</p><p class="warning" role="status">{{nativeStates[detail.status]||'状态未知'}}<span v-if="pending">。仅查询原编号，不自动重发。</span></p>
  <p v-if="detail.result?.ban_status==='committed_login_test_pending'" class="warning">封禁数据库已提交，重新登录阻断效果未核验；踢下线结果独立显示，不因踢人失败撤销封禁。</p>
  <p v-if="detail.result">游戏效果：未知 · {{nativeReasons[detail.result.reason_code]||'暂无可确认的发送说明'}}</p><p class="mono operation-number">{{detail.operation_id}}</p>
  <template v-if="detail.status==='preview'"><p class="field-hint">预览有效期至 {{new Date(detail.expires_at*1000).toLocaleString('zh-CN',{hour12:false})}}；确认时重新核对目标与能力。</p><label v-if="detail.preview.action==='native-notice'&&!attempted" class="native-check"><input v-model="ack" type="checkbox" :disabled="busy"/>我确认发送全服广播，不是单人私信</label><div class="button-row"><button :disabled="busy" @click="cancel">取消未发送预览</button><button v-if="!attempted" class="danger" :disabled="busy||!key" @click="confirm">确认执行一次</button></div></template>
  <div class="button-row"><button :disabled="busy" @click="inspect()">查询原操作结果</button><button v-if="detail.status!=='preview'" :disabled="busy||(indeterminate&&!ack)" @click="reset">结束查看，返回新操作</button></div>
  <label v-if="indeterminate&&detail.status!=='preview'" class="native-check"><input v-model="ack" type="checkbox" :disabled="busy"/>我已记录不确定操作编号；新建相同操作可能产生重复效果，原记录保留在历史中</label>
 </section>
 <p v-if="error" class="submit-error" role="alert">{{error}}</p><p v-if="busy" role="status">正在处理，请勿重复点击…</p>
 <details v-if="!detail"><summary>按历史操作编号查询</summary><div class="toolbar"><input v-model="lookup" aria-label="原生控制操作编号" placeholder="32位操作编号"/><button :disabled="busy" @click="inspect(lookup.trim())">查询历史控制</button></div></details>
 <section class="native-history"><div class="section-title"><h3>控制历史</h3><button :disabled="busy||historyBusy" @click="historyLoad">刷新控制历史</button></div><p v-if="!history.length" class="empty">暂无控制记录</p><article v-for="r in history" :key="r.operation_id"><div><b>{{nativeNames[r.action]}}</b><small>{{new Date(r.created_at*1000).toLocaleString('zh-CN',{hour12:false})}}</small></div><p>{{r.preview.target.accountname}}<span v-if="r.preview.target.uid"> · UID {{r.preview.target.uid}}</span> · {{nativeStates[r.status]||'未知'}}</p><button :disabled="busy||!!detail" @click="inspect(r.operation_id)">查看此控制结果</button></article><div class="pagination"><button :disabled="busy||historyBusy||page<=1" @click="page--;historyLoad()">上一页控制记录</button><span>第 {{page}} 页</span><button :disabled="busy||historyBusy||history.length<50" @click="page++;historyLoad()">下一页控制记录</button></div></section>
</section></template>
<style scoped>
.native-form{display:grid;gap:10px;max-width:720px}.native-form>label{display:block}.native-form>button{justify-self:start}.native-form textarea{width:100%;resize:vertical;min-height:100px}.native-check{display:flex;flex-direction:row;gap:10px;align-items:start;margin:14px 0}.native-check input{width:auto;flex:none;margin-top:4px}.native-target{padding:14px;border:1px solid var(--border-color);border-radius:12px}.native-target button{margin-left:12px}.native-preview blockquote{white-space:pre-wrap;overflow-wrap:anywhere;border-left:3px solid var(--primary-color);margin:16px 0;padding:10px 16px}.native-history{margin-top:28px}.native-history article{padding:14px 0;border-bottom:1px solid var(--border-color)}.native-history article>div{display:flex;justify-content:space-between;gap:12px}.native-history small{color:var(--text-secondary)}.native-controls .operation-number{overflow-wrap:anywhere}.native-preview .button-row{flex-wrap:wrap;gap:10px;margin:12px 0}@media(max-width:600px){.native-target strong{display:block;margin-bottom:8px}.native-target button{margin-left:0}.native-history article>div{flex-direction:column;gap:4px}.native-preview .button-row>button{flex:1 1 160px}}
</style>
