<script setup lang="ts">
import {ref,watch,onBeforeUnmount} from 'vue'
import {api,uncertainMessage} from '../api'
import Modal from './Modal.vue'
const props=withDefaults(defineProps<{uid?:number,characNo?:number,lockedTarget?:boolean,operationId?:string}>(),{uid:0,characNo:0,lockedTarget:false,operationId:''})
const emit=defineEmits<{draft:[request:any]}>()
const filterUid=ref(''),role=ref(''),op=ref(''),rows=ref<any[]>([]),page=ref(1),more=ref(false)
const error=ref(''),loading=ref(false),detailError=ref(''),detailLoading=ref(false),selected=ref(''),detail=ref<any>(null),after=ref(0),previous=ref<number[]>([])
let listEpoch=0,detailEpoch=0
const labels:Record<string,string>={unclaimed_marker:'数据库未领取',claimed_marker:'数据库已领取标记',deleted_marker:'数据库删除标记',record_missing:'记录缺失 · 领取未知'}
function time(v:string){return v?new Date(v.replace(' ','T')+'Z').toLocaleString('zh-CN',{hour12:false}):'未知'}
function validNumber(v:string){return !v||/^\d+$/.test(v)&&Number(v)>0&&Number(v)<=2147483647}
async function load(reset=false){
 const epoch=++listEpoch;error.value='';loading.value=false
 if(!validNumber(filterUid.value)||!validNumber(role.value)){error.value='账号 UID 和角色编号应为正整数。';return}
 if(op.value&&!/^[a-f0-9]{32}$/.test(op.value)){error.value='操作编号应为32位小写十六进制字符。';return}
 if(reset)page.value=1
 loading.value=true;rows.value=[];more.value=false
 try{const data=await api('/mail-center?'+new URLSearchParams({uid:filterUid.value||'0',charac_no:role.value||'0',operation_id:op.value,page:String(page.value)}));if(epoch!==listEpoch)return;rows.value=data.items;more.value=data.has_more}
 catch(e){if(epoch===listEpoch)error.value=uncertainMessage(e)}finally{if(epoch===listEpoch)loading.value=false}
}
async function inspect(id:string,cursor=0){
 const epoch=++detailEpoch;selected.value=id;after.value=cursor;detailLoading.value=true;detailError.value='';detail.value=null
 try{const data=await api('/mail-center/'+id+'?after='+cursor);if(epoch!==detailEpoch)return;detail.value=data;after.value=cursor}
 catch(e){if(epoch===detailEpoch)detailError.value=uncertainMessage(e)}finally{if(epoch===detailEpoch)detailLoading.value=false}
}
function open(id:string){previous.value=[];after.value=0;void inspect(id)}
function close(){detailEpoch++;selected.value='';detail.value=null;detailError.value='';detailLoading.value=false}
async function next(){if(detail.value?.next_after==null)return;const cursor=detail.value.next_after;previous.value.push(after.value);await inspect(selected.value,cursor)}
async function back(){const cursor=previous.value.pop();if(cursor!==undefined)await inspect(selected.value,cursor)}
function draft(){if(!detail.value)return;const request=JSON.parse(JSON.stringify(detail.value.batch.request));emit('draft',request);close()}
watch(()=>[props.uid,props.characNo,props.operationId],()=>{filterUid.value=props.uid?String(props.uid):'';role.value=props.characNo?String(props.characNo):'';op.value=props.operationId;close();void load(true);if(props.operationId)open(props.operationId)},{immediate:true})
onBeforeUnmount(()=>{listEpoch++;detailEpoch++})
</script>
<template>
 <section class="panel mail-center">
  <div class="section-title"><h2>邮件投递记录</h2><span class="pill">完整附件分页 · 只读追踪</span></div>
  <p v-if="lockedTarget" class="field-hint">收件范围固定为当前角色；如需搜索其他玩家，请使用独立邮件中心。</p>
  <form class="toolbar" @submit.prevent="load(true)">
   <label>账号 UID<input v-model="filterUid" :disabled="lockedTarget" inputmode="numeric" aria-label="邮件账号UID" placeholder="全部账号"></label>
   <label>角色编号<input v-model="role" :disabled="lockedTarget" inputmode="numeric" aria-label="邮件角色编号" placeholder="全部角色"></label>
   <label>操作编号<input v-model="op" aria-label="邮件操作编号" placeholder="精确操作编号"></label>
   <button :disabled="loading">查询邮件</button>
  </form>
  <p v-if="error" class="submit-error" role="alert">{{error}}</p>
  <p class="field-hint">展示本后台的投递流水，不包含玩家互寄邮件。领取标记来自数据库，不代表已核实游戏内效果。</p>
  <div v-if="rows.length" class="table-wrap"><table><thead><tr><th>时间 / 操作编号</th><th>收件人</th><th>附件记录</th><th>邮件文字</th><th>操作</th></tr></thead><tbody>
   <tr v-for="r in rows" :key="r.operation_id"><td>{{time(r.created_at)}}<small class="cell-note">{{r.operation_id}}</small></td><td><b>{{r.character_name}}</b><small class="cell-note">{{r.account_name}} · UID {{r.target_uid}} · 角色 #{{r.charac_no}}</small></td><td>{{Number(r.postal_count).toLocaleString()}} 条<small v-if="!r.history_complete" class="cell-note">历史已找回 {{r.recorded_count}} 条，记录不完整</small></td><td>{{r.message}}</td><td><button @click="open(r.operation_id)">查看全部附件</button></td></tr>
  </tbody></table></div>
  <p v-else class="empty">{{loading?'正在查询投递记录…':'没有符合条件的邮件投递记录。'}}</p>
  <div class="pagination"><button :disabled="loading||page<=1" @click="page--;load()">上一页邮件</button><span>第 {{page}} 页</span><button :disabled="loading||!more" @click="page++;load()">下一页邮件</button></div>
 </section>
 <Modal v-if="selected" title="邮件投递详情" @close="close">
  <p v-if="detailLoading" role="status">正在读取附件记录…</p>
  <div v-if="detailError" class="submit-error" role="alert">{{detailError}} <button @click="inspect(selected,after)">重试查询</button></div>
  <template v-if="detail">
   <p><b>{{detail.batch.character_name}}</b> · {{detail.batch.account_name}} · 角色 #{{detail.batch.charac_no}}</p>
   <p>操作编号 {{selected}} · 信件 #{{detail.batch.letter_id}}</p>
   <p style="white-space:pre-wrap">{{detail.batch.message}}</p>
   <p v-if="detail.batch.request.template_id">来源礼包 #{{detail.batch.request.template_id}} / v{{detail.batch.request.template_version}}{{detail.batch.request.template_overrides?' · 已临时调整（原模板未修改）':''}}</p>
   <p v-if="!detail.batch.history_complete" class="submit-error">历史附件信息不完整。找回 {{detail.batch.recorded_count}} / {{detail.batch.postal_count}} 条，未找回记录不能视为已领取。</p>
   <div class="table-wrap mail-receipts"><table><thead><tr><th>序号 / 邮件附件ID</th><th>物品编号</th><th>数量</th><th>金币</th><th>状态</th></tr></thead><tbody><tr v-for="r in detail.items" :key="r.ordinal"><td data-label="序号 / 邮件附件ID">{{r.ordinal}} / {{r.postal_id}}</td><td data-label="物品编号">{{r.item_id||'纯金币'}}</td><td data-label="数量">{{r.quantity}}</td><td data-label="金币">{{Number(r.gold).toLocaleString()}}</td><td data-label="领取状态">{{labels[r.receipt_state]||'未知'}}<small v-if="r.receipt_state==='claimed_marker'" class="cell-note">{{time(r.receive_time)}}</small></td></tr></tbody></table></div>
   <p class="field-hint">{{detail.note}}</p>
   <div class="pagination"><button :disabled="detailLoading||!previous.length" @click="back">上一页附件</button><span>已记录 {{detail.batch.recorded_count}} 条</span><button :disabled="detailLoading||detail.next_after==null" @click="next">下一页附件</button></div>
  </template>
  <template #footer><button :disabled="!detail||detailLoading" @click="draft">复制为新发放草稿</button><button @click="close">关闭</button></template>
 </Modal>
</template>

<style scoped>
.mail-center .toolbar label{flex:1;min-width:10rem}.mail-center code{overflow-wrap:anywhere}
@media(max-width:600px){
 .mail-center .toolbar label{flex-basis:100%}
 .mail-receipts table,.mail-receipts tbody{display:block;width:100%;min-width:0}
 .mail-receipts thead{display:none}
 .mail-receipts tr{display:block;border-bottom:1px solid var(--border-color);padding:10px}
 .mail-receipts td{display:flex;justify-content:space-between;gap:12px;padding:5px 0;border:0;white-space:normal;text-align:right;flex-wrap:wrap}
 .mail-receipts td::before{content:attr(data-label);color:var(--text-secondary);text-align:left}
 .mail-receipts .cell-note{width:100%}
}
</style>
