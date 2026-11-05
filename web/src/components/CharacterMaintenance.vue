<script setup lang="ts">
import {ref,computed,onMounted,onBeforeUnmount,watch,nextTick} from 'vue'
import {api,ApiError,uncertainMessage} from '../api'
import {inventoryStates as states} from '../nativeStatus'
const props=defineProps<{characNo:number}>()
const emit=defineEmits(['busy','pending','reauth','expired','changed'])
const base='/character-maintenance',storage='dnfgm-character-maintenance-operation'
const current=ref<any>(null),operation=ref<any>(null),records=ref<any[]>([]),page=ref(1),more=ref(false)
const busy=ref(false),error=ref(''),reason=ref(''),reasonError=ref(''),valueError=ref(''),lookup=ref('')
const normal=ref('0'),premium=ref('0'),key=ref(''),attempted=ref(false),root=ref<HTMLElement|null>(null)
const unfinished=computed(()=>operation.value?.status==='preview'||operation.value?.status==='executing')
const pending=computed(()=>operation.value?.status==='executing'||attempted.value&&operation.value?.status==='preview')
const labels:Record<string,string>={fatigue:'普通已消耗疲劳',premium_fatigue:'额外已消耗疲劳'}
let alive=true,timer:ReturnType<typeof setInterval>|undefined
watch(busy,v=>emit('busy',v));watch(unfinished,v=>emit('pending',v))
function failure(e:unknown){error.value=uncertainMessage(e);if(e instanceof ApiError&&e.status===401)emit('expired');if(e instanceof ApiError&&e.status===403&&e.message.includes('重新认证'))emit('reauth')}
function remember(id:string){try{sessionStorage.setItem(storage,id)}catch{/* history lookup remains available */}}
async function run(fn:()=>Promise<void>){if(busy.value)return;busy.value=true;error.value='';try{await fn()}catch(e){if(alive)failure(e)}finally{if(alive)busy.value=false}}
async function refresh(){await run(async()=>{const r=await api(`${base}/characters/${props.characNo}`);if(alive){current.value=r;normal.value=String(r.archive.fatigue);premium.value=String(r.archive.premium_fatigue)}})}
async function history(){await run(async()=>{const r=await api(`${base}/operations?charac_no=${props.characNo}&page=${page.value}`);if(alive){records.value=r.items;more.value=r.has_more}})}
function received(r:any){if(!alive)return;operation.value=r;remember(r.operation_id);if(r.status==='committed')emit('changed')}
async function inspect(id=operation.value?.operation_id){if(!id||!/^[a-f0-9]{32}$/.test(id)){error.value='请输入32位操作编号';return}await run(async()=>{received(await api(`${base}/operations/${id}`));attempted.value=true})}
async function preview(){
 if(busy.value||operation.value||!current.value)return
 reasonError.value=reason.value.trim()?'':'请填写操作原因';valueError.value=''
 const values=[normal.value,premium.value];if(values.some(v=>!/^\d+$/.test(v)||Number(v)>32767))valueError.value='疲劳须为0至32767的整数；填0恢复该项。'
 if(reasonError.value||valueError.value){await nextTick();root.value?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();return}
 await run(async()=>{const r=await api(base+'/preview','POST',{action:'char-fatigue',uid:current.value.target.uid,charac_no:props.characNo,reference:current.value.reference,changes:{fatigue:Number(normal.value),premium_fatigue:Number(premium.value)},reason:reason.value.trim()});key.value=crypto.randomUUID().replaceAll('-','');attempted.value=false;received(r);await nextTick();root.value?.querySelector<HTMLElement>('.fatigue-preview')?.scrollIntoView?.({block:'nearest'})})
}
async function confirm(){if(!operation.value||attempted.value||!key.value)return;attempted.value=true;await run(async()=>received(await api(`${base}/operations/${operation.value.operation_id}/confirm`,'POST',{idempotency_key:key.value})))}
async function cancel(){await run(async()=>received(await api(`${base}/operations/${operation.value.operation_id}/cancel-preview`,'POST',{})))}
async function finish(){operation.value=null;attempted.value=false;key.value='';try{sessionStorage.removeItem(storage)}catch{}await refresh();await history()}
onMounted(async()=>{await refresh();if(!alive)return;await history();if(!alive)return;let id='';try{id=sessionStorage.getItem(storage)||''}catch{}if(id)await inspect(id);timer=setInterval(()=>{if(alive&&pending.value&&!document.hidden&&!busy.value)void inspect()},10000)})
onBeforeUnmount(()=>{alive=false;if(timer)clearInterval(timer);emit('busy',false);emit('pending',false)})
</script>
<template><section ref="root" class="fatigue-maintenance">
 <h3>角色疲劳恢复／调整</h3>
 <p class="notice">这是维护存档操作，不是在线热更新。请先在「维护中心」显式开启维护窗口，完成后关闭窗口让游戏重新加载。本页不会自动停止游戏。</p>
 <p v-if="error" class="submit-error" role="alert">{{error}}</p>
 <template v-if="current">
  <p><b>{{current.target.accountname}}</b> / UID {{current.target.uid}} · {{current.target.character.charac_name}} / #{{current.target.character.charac_no}}</p>
  <dl class="character-facts"><div><dt>普通消耗 / 上限</dt><dd>{{current.archive.fatigue}} / {{current.archive.max_fatigue}}</dd></div><div><dt>额外消耗 / 上限</dt><dd>{{current.archive.premium_fatigue}} / {{current.archive.max_premium_fatigue}}</dd></div><div><dt>历史 used_fatigue</dt><dd>{{current.archive.used_fatigue}}（保持不变）</dd></div></dl>
  <p class="field-hint">{{current.note}}</p>
  <p v-if="!current.enabled" class="warning">请在「功能与权限」开启「角色疲劳恢复／调整」。</p>
  <p v-if="!current.maintenance.available" class="warning">{{current.maintenance.note}}</p>
  <button :disabled="busy||unfinished" @click="refresh">刷新存档及维护状态</button>
  <form v-if="!operation" @submit.prevent="preview" novalidate>
   <div class="fatigue-fields"><label>普通已消耗疲劳<input v-model="normal" inputmode="numeric" :disabled="busy" :aria-invalid="!!valueError" aria-describedby="fatigue-value-error"></label><label>额外已消耗疲劳<input v-model="premium" inputmode="numeric" :disabled="busy" :aria-invalid="!!valueError" aria-describedby="fatigue-value-error"></label></div>
   <p v-if="valueError" id="fatigue-value-error" class="submit-error" role="alert">{{valueError}}</p>
   <button type="button" :disabled="busy" @click="normal='0';premium='0'">恢复两项疲劳（设为0）</button>
   <label>操作原因<input v-model="reason" :disabled="busy" maxlength="200" :aria-invalid="!!reasonError" aria-describedby="fatigue-reason-error" @input="reasonError=''" placeholder="例如：角色疲劳恢复"></label>
   <p v-if="reasonError" id="fatigue-reason-error" class="submit-error" role="alert">{{reasonError}}</p>
   <button class="primary" :disabled="busy||!current.enabled||!current.maintenance.available" type="submit">生成疲劳调整预览</button>
  </form>
 </template>
 <section v-if="operation" class="fatigue-preview">
  <h4>{{states[operation.status]||operation.status}}</h4>
  <p>目标：{{operation.preview.target.accountname}} / UID {{operation.preview.target.uid}} · {{operation.preview.target.character.charac_name}} / #{{operation.preview.target.character.charac_no}}</p>
  <p>操作编号：{{operation.operation_id}}</p><p>原因：{{operation.preview.reason}}</p>
  <dl class="character-facts"><div v-for="(v,k) in operation.preview.changes" :key="k"><dt>{{labels[String(k)]}}</dt><dd>{{(v as any).before}} → {{(v as any).after}}</dd></div></dl>
  <p v-if="pending" class="notice">结果待核对，正在定时查询原编号。不会自动重复提交。</p>
  <p v-if="operation.status==='committed'" class="notice">存档、快照与成功审计已提交；游戏内效果未由此证明。请结束维护后查看。</p>
  <div class="button-row"><button v-if="operation.status==='preview'&&!attempted&&key" class="danger" :disabled="busy" @click="confirm">确认修改疲劳</button><button :disabled="busy" @click="inspect()">查询原操作结果</button><button v-if="operation.status==='preview'&&!pending" :disabled="busy" @click="cancel">取消预览</button><button v-if="['committed','cancelled','aborted'].includes(operation.status)" :disabled="busy" @click="finish">结束查看</button></div>
 </section>
 <details><summary>按操作编号查询</summary><input v-model="lookup" aria-label="疲劳操作编号"><button :disabled="busy||!!operation" @click="inspect(lookup.trim())">查询疲劳操作</button></details>
 <h4>角色疲劳维护历史</h4><p v-if="!records.length">暂无记录</p>
 <article v-for="r in records" :key="r.operation_id"><span>{{states[r.status]||r.status}} · {{r.preview.reason}}</span><button :disabled="busy||!!operation" @click="inspect(r.operation_id)">查看记录</button></article>
 <div class="button-row"><button :disabled="busy||page<=1" @click="page--;history()">上一页</button><span>第 {{page}} 页</span><button :disabled="busy||!more" @click="page++;history()">下一页</button></div>
 <p v-if="busy" role="status">正在处理…</p>
</section></template>
<style scoped>
.fatigue-maintenance{display:grid;gap:12px}.fatigue-maintenance form{display:grid;gap:12px}.fatigue-fields{display:grid;grid-template-columns:1fr 1fr;gap:16px}label{display:grid;gap:6px}.fatigue-preview{padding:16px;border:1px solid var(--border-color);border-radius:12px;background:var(--bg-secondary)}.button-row{display:flex;align-items:center;flex-wrap:wrap;gap:10px}article{display:flex;justify-content:space-between;align-items:center;gap:10px}p{overflow-wrap:anywhere}@media(max-width:600px){.fatigue-fields{grid-template-columns:1fr}}
</style>
