<script setup lang="ts">
import {ref,nextTick} from 'vue'
import Modal from './Modal.vue'
import FieldError from './FieldError.vue'
import {api,ApiError,uncertainMessage} from '../api'
const props=defineProps<{item?:any,filters:Record<string,unknown>}>()
const emit=defineEmits<{close:[],changed:[],reauth:[],expired:[]}>()
const enabled=ref(!props.item?.sendable),reason=ref(''),busy=ref(false),error=ref(''),reasonError=ref('')
const preview=ref<any>(null),result=ref<any>(null),uncertain=ref(false),key=ref(''),published=ref(false)
const categories:Record<string,string>={equipment:'装备',material:'材料',consumable:'消耗品',special:'特殊'}
async function fail(e:unknown){error.value=uncertainMessage(e);if(e instanceof ApiError&&e.status===401){emit('expired');return}if(e instanceof ApiError&&e.status===403&&e.message.includes('重新认证'))emit('reauth');await nextTick();document.querySelector<HTMLElement>('[data-policy-error]')?.focus()}
async function makePreview(){
 if(busy.value)return
 error.value='';reasonError.value=''
 if(!reason.value.trim()){reasonError.value='请填写本次策略变更原因。';await nextTick();document.getElementById('policy-reason')?.focus();return}
 busy.value=true
 try{preview.value=await api('/catalog/policy/preview','POST',{item_id:props.item?.id??null,filters:props.filters,enabled:enabled.value,reason:reason.value.trim()});key.value=crypto.randomUUID();uncertain.value=false}catch(e){await fail(e)}finally{busy.value=false}
}
function committed(d:any){result.value=d;uncertain.value=false;if(!published.value){published.value=true;emit('changed')}}
async function confirm(){
 if(busy.value||uncertain.value||result.value)return
 busy.value=true;error.value=''
 try{uncertain.value=true;committed(await api('/operations/'+preview.value.operation_id+'/confirm','POST',{idempotency_key:key.value}))}catch(e){if(e instanceof ApiError&&[401,403,404,409,422].includes(e.status))uncertain.value=false;await fail(e)}finally{busy.value=false}
}
async function query(){
 if(busy.value)return
 busy.value=true;error.value=''
 try{const d=await api('/operations/'+preview.value.operation_id);if(d.status==='committed')committed(d.result);else error.value='尚未查到已提交结果。请保留原编号；不要新建同一变更。'}catch(e){await fail(e)}finally{busy.value=false}
}
</script>
<template>
 <Modal title="物品发放策略" :busy="busy" @close="emit('close')">
  <div class="catalog-policy">
   <p v-if="item"><b>{{item.name}}</b> <span class="mono">#{{item.id}}</span><small class="cell-note">{{item.policy_reason}}</small></p>
   <template v-else><p><b>作用于完整筛选结果，不仅是当前页。</b></p><dl class="character-facts"><div><dt>名称或编号</dt><dd>{{filters.q||'不限'}}</dd></div><div><dt>物品类型</dt><dd>{{categories[String(filters.category)]||'所有类型（仅支持普通物品）'}}</dd></div><div><dt>发放状态</dt><dd>{{filters.allowed_only?'仅可发放':'全部状态'}}</dd></div></dl></template>
   <p class="field-hint">开放仅表示“允许试发、未验证”。原19项只做过元数据审核，也不冒充客户端已验证。特殊类型、未知堆叠上限不能开放；版本、数量与20条附件限制仍然生效。</p>
   <template v-if="!preview">
    <label>变更方式<select v-model="enabled" :disabled="busy" aria-label="策略变更方式"><option :value="true">允许试发（未验证）</option><option :value="false">禁止发放</option></select></label>
    <label for="policy-reason">操作原因 <i class="required-tag">必填</i></label><input id="policy-reason" v-model="reason" maxlength="200" :disabled="busy" :aria-invalid="!!reasonError" aria-describedby="policy-reason-error" placeholder="例如：开放普通材料用于活动试发" @input="reasonError=''" @keydown.enter.prevent="makePreview">
    <FieldError id="policy-reason-error" :message="reasonError"/>
   </template>
   <template v-else>
    <h3>{{enabled?'允许试发':'禁止发放'}} · 变更预览</h3>
    <div class="character-metrics"><article><span>全部匹配</span><strong>{{preview.preview.matched}}</strong></article><article><span>实际变更</span><strong>{{preview.preview.affected}}</strong></article><article><span>不支持，跳过</span><strong>{{preview.preview.skipped}}</strong></article></div>
    <p>保持不变 {{preview.preview.unchanged}} 项 · 策略版本 {{preview.preview.policy_revision}} · 5分钟内有效</p><p>原因：{{reason}}</p>
    <p class="mono operation-number">操作编号 {{preview.operation_id}}</p><p class="field-hint">策略或PVF变化必须重新预览。确认只调整发放资格，不发送物品、不修改已有邮件或玩家背包。</p>
   </template>
   <p v-if="uncertain" class="warning" role="status">结果待确认：不要重复提交。请按原编号查询；关闭前复制操作编号，也可稍后在操作审计中查询。</p>
   <p v-if="result" class="submit-success" role="status">策略已保存，实际变更 {{result.affected}} 项，当前版本 {{result.policy_revision}}。尚未进行任何物品发放。</p>
  </div>
  <template #footer>
   <p v-if="error" class="submit-error" role="alert" tabindex="-1" data-policy-error>{{error}}</p>
   <button :disabled="busy" @click="emit('close')">{{result?'完成':'关闭'}}</button>
   <button v-if="preview&&!result" :disabled="busy" @click="query">按原编号查询结果</button>
   <button v-if="preview&&!result&&!uncertain" :disabled="busy" @click="preview=null;error=''">返回修改</button>
   <button v-if="!preview" class="primary" :disabled="busy" @click="makePreview">预览影响范围</button>
   <button v-else-if="!result" class="primary" :disabled="busy||uncertain" @click="confirm">{{busy?'正在处理…':'确认变更一次'}}</button>
  </template>
 </Modal>
</template>
