<script setup lang="ts">
import {ref,computed,onMounted,onBeforeUnmount,watch,nextTick} from 'vue'
import {api,ApiError,uncertainMessage} from '../api'
import {inventoryStates as states} from '../nativeStatus'
const props=defineProps<{characNo:number,selection?:number}>()
const emit=defineEmits(['busy','pending','reauth','expired','changed'])
const base='/quest-repairs',storage='dnfgm-quest-repair-operation:'+props.characNo
const current=ref<any>(null),operation=ref<any>(null),records=ref<any[]>([]),page=ref(1),more=ref(false)
const busy=ref(false),error=ref(''),reason=ref(''),reasonError=ref(''),lookup=ref('')
const slot=ref<number>(0),slotError=ref('')
const candidates=computed(()=>current.value?.slots?.filter((s:any)=>s.id||s.trigger_raw)||[])
const key=ref(''),attempted=ref(false),root=ref<HTMLElement|null>(null)
const unfinished=computed(()=>operation.value?.status==='preview'||operation.value?.status==='executing')
const pending=computed(()=>operation.value?.status==='executing'||attempted.value&&operation.value?.status==='preview')
const labels:Record<string,string>={id:'任务编号',trigger_raw:'原始进度'}
let alive=true,timer:ReturnType<typeof setInterval>|undefined
watch(()=>props.selection,v=>{if(!operation.value&&v)slot.value=v},{immediate:true})
watch(busy,v=>emit('busy',v));watch(unfinished,v=>emit('pending',v))
function failure(e:unknown){error.value=uncertainMessage(e);if(e instanceof ApiError&&e.status===401)emit('expired');if(e instanceof ApiError&&e.status===403&&e.message.includes('重新认证'))emit('reauth')}
function remember(id:string){try{sessionStorage.setItem(storage,id)}catch{/* history lookup remains available */}}
async function run(fn:()=>Promise<void>){if(busy.value)return;busy.value=true;error.value='';try{await fn()}catch(e){if(alive)failure(e)}finally{if(alive)busy.value=false}}
async function refresh(){await run(async()=>{const r=await api(`${base}/characters/${props.characNo}`);if(alive){current.value=r}})}
async function history(){await run(async()=>{const r=await api(`${base}/operations?charac_no=${props.characNo}&page=${page.value}`);if(alive){records.value=r.items;more.value=r.has_more}})}
function received(r:any){if(!alive)return;operation.value=r;remember(r.operation_id);if(r.status==='committed')emit('changed')}
async function inspect(id=operation.value?.operation_id){if(!id||!/^[a-f0-9]{32}$/.test(id)){error.value='请输入32位操作编号';return}await run(async()=>{const r=await api(`${base}/operations/${id}`);if(r.request.charac_no!==props.characNo){error.value='该操作属于其他角色，请到对应角色或管理记录中查询';return}received(r);attempted.value=true})}
async function preview(){
 if(busy.value||operation.value||!current.value)return
 slotError.value=candidates.value.some((s:any)=>s.slot===slot.value)?'':'请选择一个非空任务槽或残留进度槽'
 reasonError.value=reason.value.trim()?'':'请填写操作原因'
 if(reasonError.value||slotError.value){await nextTick();root.value?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();return}
 await run(async()=>{const r=await api(base+'/preview','POST',{action:'quest-clear',slot:slot.value,uid:current.value.target.uid,charac_no:props.characNo,reference:current.value.reference,reason:reason.value.trim()});key.value=crypto.randomUUID().replaceAll('-','');attempted.value=false;received(r);await nextTick();root.value?.querySelector<HTMLElement>('.quest-preview')?.scrollIntoView?.({block:'nearest'})})
}
async function confirm(){if(!operation.value||attempted.value||!key.value)return;attempted.value=true;await run(async()=>received(await api(`${base}/operations/${operation.value.operation_id}/confirm`,'POST',{idempotency_key:key.value})))}
async function cancel(){await run(async()=>received(await api(`${base}/operations/${operation.value.operation_id}/cancel-preview`,'POST',{})))}
async function finish(){operation.value=null;attempted.value=false;key.value='';try{sessionStorage.removeItem(storage)}catch{}await refresh();await history()}
onMounted(async()=>{await refresh();if(!alive)return;await history();if(!alive)return;let id='';try{id=sessionStorage.getItem(storage)||''}catch{}if(id)await inspect(id);timer=setInterval(()=>{if(alive&&pending.value&&!document.hidden&&!busy.value)void inspect()},10000)})
onBeforeUnmount(()=>{alive=false;if(timer)clearInterval(timer);emit('busy',false);emit('pending',false)})
</script>
<template><section ref="root" class="quest-maintenance">
 <h3>单任务槽清理</h3>
 <p class="notice">这是维护存档操作，不是在线热更新。请先在「维护中心」显式开启维护窗口，完成后关闭窗口让游戏重新加载。本页不会自动停止游戏。</p>
 <p v-if="error" class="submit-error" role="alert">{{error}}</p>
 <template v-if="current">
  <p><b>{{current.target.accountname}}</b> / UID {{current.target.uid}} · {{current.target.character.charac_name}} / #{{current.target.character.charac_no}}</p>
  <p class="notice">{{current.note}}</p>
  <p v-if="!current.supported" class="warning">当前程序版本不支持任务写入，请核对部署版本。</p>
  <p v-if="!current.enabled" class="warning">请在「功能与版本」开启「单任务槽清理」。</p>
  <p v-if="!current.maintenance.available" class="warning">{{current.maintenance.note}}</p>
  <button :disabled="busy||unfinished" @click="refresh">刷新存档及维护状态</button>
  <form v-if="!operation" @submit.prevent="preview" novalidate>
   <label>指定任务槽<select v-model="slot" :disabled="busy" :aria-invalid="!!slotError" aria-describedby="quest-slot-error" @change="slotError=''">
    <option :value="0">请选择要清理的一个槽位</option>
    <option v-for="s in candidates" :key="s.slot" :value="s.slot">槽 {{s.slot}} · #{{s.id}} {{s.definition?.name|| (s.id?'无可用名称':'空槽残留')}} · 进度 {{s.trigger_raw}}</option>
   </select></label>
   <p v-if="slotError" id="quest-slot-error" class="submit-error" role="alert">{{slotError}}</p>
   <p v-if="!candidates.length" class="field-hint">20个任务槽均为空且没有残留进度，无需清理。</p>
   <label>操作原因<input v-model="reason" :disabled="busy" maxlength="200" :aria-invalid="!!reasonError" aria-describedby="quest-reason-error" @input="reasonError=''" placeholder="例如：指定任务卡住，清理该进行中槽"></label>
   <p v-if="reasonError" id="quest-reason-error" class="submit-error" role="alert">{{reasonError}}</p>
   <button class="primary" :disabled="busy||!current.enabled||!current.supported||!current.maintenance.available||!candidates.length" type="submit">生成单任务清理预览</button>
  </form>
 </template>
 <section v-if="operation" class="quest-preview">
  <h4>{{states[operation.status]||operation.status}}</h4>
  <p>目标：{{operation.preview.target.accountname}} / UID {{operation.preview.target.uid}} · {{operation.preview.target.character.charac_name}} / #{{operation.preview.target.character.charac_no}}</p>
  <p>所选槽：{{operation.preview.slot}} · {{operation.preview.quest_name||'无可用任务名称'}} · 其余19槽、完成标记、紧急任务和通知存档不变。</p>
  <p>操作编号：{{operation.operation_id}}</p><p>原因：{{operation.preview.reason}}</p>
  <dl class="character-facts"><div v-for="(v,k) in operation.preview.changes" :key="k"><dt>{{labels[String(k)]}}</dt><dd>{{(v as any).before}} → {{(v as any).after}}</dd></div></dl>
  <p v-if="pending" class="notice">结果待核对，正在定时查询原编号。不会自动重复提交。</p>
  <p v-if="operation.status==='committed'" class="notice">存档、快照与成功审计已提交；游戏内效果未由此证明。请结束维护后查看。</p>
  <div class="button-row"><button v-if="operation.status==='preview'&&!attempted&&key" class="danger" :disabled="busy" @click="confirm">确认清理这一个任务槽</button><button :disabled="busy" @click="inspect()">查询原操作结果</button><button v-if="operation.status==='preview'&&!pending" :disabled="busy" @click="cancel">取消预览</button><button v-if="['committed','cancelled','aborted'].includes(operation.status)" :disabled="busy" @click="finish">结束查看</button></div>
 </section>
 <details><summary>按操作编号查询</summary><input v-model="lookup" aria-label="任务修复操作编号"><button :disabled="busy||!!operation" @click="inspect(lookup.trim())">查询任务修复操作</button></details>
 <h4>单任务槽清理历史</h4><p v-if="!records.length">暂无记录</p>
 <article v-for="r in records" :key="r.operation_id"><span>{{states[r.status]||r.status}} · {{r.preview.reason}}</span><button :disabled="busy||!!operation" @click="inspect(r.operation_id)">查看记录</button></article>
 <div class="button-row"><button :disabled="busy||page<=1" @click="page--;history()">上一页</button><span>第 {{page}} 页</span><button :disabled="busy||!more" @click="page++;history()">下一页</button></div>
 <p v-if="busy" role="status">正在处理…</p>
</section></template>
<style scoped>
.quest-maintenance{display:grid;gap:12px}.quest-maintenance form{display:grid;gap:12px}.quest-fields{display:grid;grid-template-columns:1fr 1fr;gap:16px}label{display:grid;gap:6px}.quest-preview{padding:16px;border:1px solid var(--border-color);border-radius:12px;background:var(--bg-secondary)}.button-row{display:flex;align-items:center;flex-wrap:wrap;gap:10px}article{display:flex;justify-content:space-between;align-items:center;gap:10px}p{overflow-wrap:anywhere}@media(max-width:600px){.quest-fields{grid-template-columns:1fr}}
</style>
