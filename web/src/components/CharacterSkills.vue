<script setup lang="ts">
import {ref,computed,onMounted,onBeforeUnmount,watch,nextTick} from 'vue'
import {api,ApiError,uncertainMessage} from '../api'
import {inventoryStates as states} from '../nativeStatus'
const props=defineProps<{characNo:number}>()
const emit=defineEmits(['busy','pending','reauth','expired','changed'])
const base='/character-skills',storage='dnfgm-character-skill-points-operation'
const current=ref<any>(null),operation=ref<any>(null),records=ref<any[]>([]),page=ref(1),more=ref(false)
const busy=ref(false),error=ref(''),reason=ref(''),reasonError=ref(''),valueError=ref(''),lookup=ref('')
const values=ref<Record<string,string>>({}),key=ref(''),attempted=ref(false),root=ref<HTMLElement|null>(null)
const unfinished=computed(()=>operation.value?.status==='preview'||operation.value?.status==='executing')
const pending=computed(()=>operation.value?.status==='executing'||attempted.value&&operation.value?.status==='preview')
const labels:Record<string,string>={remain_sp:'技能树一 · 剩余SP',remain_sp_2nd:'技能树二 · 剩余SP',remain_sfp_1st:'技能树一 · 剩余TP',remain_sfp_2nd:'技能树二 · 剩余TP'}
let alive=true,timer:ReturnType<typeof setInterval>|undefined
watch(busy,v=>emit('busy',v));watch(unfinished,v=>emit('pending',v))
function failure(e:unknown){error.value=uncertainMessage(e);if(e instanceof ApiError&&e.status===401)emit('expired');if(e instanceof ApiError&&e.status===403&&e.message.includes('重新认证'))emit('reauth')}
function remember(id:string){try{sessionStorage.setItem(storage,id)}catch{/* history lookup remains available */}}
async function run(fn:()=>Promise<void>){if(busy.value)return;busy.value=true;error.value='';try{await fn()}catch(e){if(alive)failure(e)}finally{if(alive)busy.value=false}}
async function refresh(){await run(async()=>{const r=await api(`${base}/characters/${props.characNo}`);if(alive){current.value=r;values.value=Object.fromEntries(Object.keys(labels).map(k=>[k,String(r.archive[k])]))}})}
async function history(){await run(async()=>{const r=await api(`${base}/operations?charac_no=${props.characNo}&page=${page.value}`);if(alive){records.value=r.items;more.value=r.has_more}})}
function received(r:any){if(!alive)return;operation.value=r;remember(r.operation_id);if(r.status==='committed')emit('changed')}
async function inspect(id=operation.value?.operation_id){if(!id||!/^[a-f0-9]{32}$/.test(id)){error.value='请输入32位操作编号';return}await run(async()=>{received(await api(`${base}/operations/${id}`));attempted.value=true})}
async function preview(){
 if(busy.value||operation.value||!current.value)return
 reasonError.value=reason.value.trim()?'':'请填写操作原因';valueError.value=''
 if(Object.keys(labels).some(k=>!/^\d+$/.test(values.value[k]||'')||Number(values.value[k])>current.value.limits[k]))valueError.value='请填写范围内的非负整数：SP最多1073741823，TP最多2147483647。'
 if(!valueError.value&&Object.keys(labels).every(k=>Number(values.value[k])===current.value.archive[k]))valueError.value='点数没有变化，请先调整需要修改的项目。'
 if(reasonError.value||valueError.value){await nextTick();root.value?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();return}
 await run(async()=>{const r=await api(base+'/preview','POST',{action:'char-sp-tp',uid:current.value.target.uid,charac_no:props.characNo,reference:current.value.reference,changes:Object.fromEntries(Object.keys(labels).filter(k=>Number(values.value[k])!==current.value.archive[k]).map(k=>[k,Number(values.value[k])])),reason:reason.value.trim()});key.value=crypto.randomUUID().replaceAll('-','');attempted.value=false;received(r);await nextTick();root.value?.querySelector<HTMLElement>('.skill-points-preview')?.scrollIntoView?.({block:'nearest'})})
}
async function confirm(){if(!operation.value||attempted.value||!key.value)return;attempted.value=true;await run(async()=>received(await api(`${base}/operations/${operation.value.operation_id}/confirm`,'POST',{idempotency_key:key.value})))}
async function cancel(){await run(async()=>received(await api(`${base}/operations/${operation.value.operation_id}/cancel-preview`,'POST',{})))}
async function finish(){operation.value=null;attempted.value=false;key.value='';try{sessionStorage.removeItem(storage)}catch{}await refresh();await history()}
onMounted(async()=>{await refresh();if(!alive)return;await history();if(!alive)return;let id='';try{id=sessionStorage.getItem(storage)||''}catch{}if(id)await inspect(id);timer=setInterval(()=>{if(alive&&pending.value&&!document.hidden&&!busy.value)void inspect()},10000)})
onBeforeUnmount(()=>{alive=false;if(timer)clearInterval(timer);emit('busy',false);emit('pending',false)})
</script>
<template><section ref="root" class="skill-points-maintenance">
 <h3>SP／TP技能点维护</h3>
 <p class="notice">仅调整未使用SP／TP，不会洗掉已学技能，也不会重置职业。不是在线热更新。请先在「维护中心」显式开启维护窗口，完成后关闭窗口让游戏重新加载。本页不会自动停止游戏。</p>
 <p v-if="error" class="submit-error" role="alert">{{error}}</p>
 <template v-if="current">
  <p><b>{{current.target.accountname}}</b> / UID {{current.target.uid}} · {{current.target.character.charac_name}} / #{{current.target.character.charac_no}}</p>
  <dl class="character-facts"><div v-for="(label,k) in labels" :key="k"><dt>{{label}}</dt><dd>{{current.archive[k].toLocaleString('zh-CN')}}</dd></div></dl>
  <p class="field-hint">等级 {{current.archive.context.lev}} · 当前技能树索引 {{current.archive.context.skill_tree_index}}。下方填写的是修改后的剩余点数，不是增减量。</p>
  <p class="field-hint">{{current.note}}</p>
  <p v-if="!current.enabled" class="warning">请在「功能与权限」开启「SP／TP技能点维护」。</p>
  <p v-if="!current.maintenance.available" class="warning">{{current.maintenance.note}}</p>
  <button :disabled="busy||unfinished" @click="refresh">刷新存档及维护状态</button>
  <form v-if="!operation" @submit.prevent="preview" novalidate>
   <div class="skill-points-fields"><label v-for="(label,k) in labels" :key="k">{{label}}<input v-model="values[k]" inputmode="numeric" :disabled="busy" :aria-invalid="!!valueError" aria-describedby="skill-points-value-error"><small>0–{{current.limits[k].toLocaleString('zh-CN')}}</small></label></div>
   <p v-if="valueError" id="skill-points-value-error" class="submit-error" role="alert">{{valueError}}</p>
   <label>操作原因<input v-model="reason" :disabled="busy" maxlength="200" :aria-invalid="!!reasonError" aria-describedby="skill-points-reason-error" @input="reasonError=''" placeholder="例如：补偿角色技能点"></label>
   <p v-if="reasonError" id="skill-points-reason-error" class="submit-error" role="alert">{{reasonError}}</p>
   <button class="primary" :disabled="busy||!current.enabled||!current.maintenance.available" type="submit">生成技能点调整预览</button>
  </form>
 </template>
 <section v-if="operation" class="skill-points-preview">
  <h4>{{states[operation.status]||operation.status}}</h4>
  <p>目标：{{operation.preview.target.accountname}} / UID {{operation.preview.target.uid}} · {{operation.preview.target.character.charac_name}} / #{{operation.preview.target.character.charac_no}}</p>
  <p>操作编号：{{operation.operation_id}}</p><p>原因：{{operation.preview.reason}}</p>
  <dl class="character-facts"><div v-for="(v,k) in operation.preview.changes" :key="k"><dt>{{labels[String(k)]}}</dt><dd>{{(v as any).before}} → {{(v as any).after}}</dd></div></dl>
  <p v-if="pending" class="notice">结果待核对，正在定时查询原编号。不会自动重复提交。</p>
  <p v-if="operation.status==='committed'" class="notice">存档、快照与成功审计已提交；游戏内效果未由此证明。请结束维护后查看。</p>
  <div class="button-row"><button v-if="operation.status==='preview'&&!attempted&&key" class="danger" :disabled="busy" @click="confirm">确认修改技能点</button><button :disabled="busy" @click="inspect()">查询原操作结果</button><button v-if="operation.status==='preview'&&!pending" :disabled="busy" @click="cancel">取消预览</button><button v-if="['committed','cancelled','aborted'].includes(operation.status)" :disabled="busy" @click="finish">结束查看</button></div>
 </section>
 <details><summary>按操作编号查询</summary><input v-model="lookup" aria-label="技能点操作编号"><button :disabled="busy||!!operation" @click="inspect(lookup.trim())">查询技能点操作</button></details>
 <h4>技能点维护历史</h4><p v-if="!records.length">暂无记录</p>
 <article v-for="r in records" :key="r.operation_id"><span>{{states[r.status]||r.status}} · {{r.preview.reason}}</span><button :disabled="busy||!!operation" @click="inspect(r.operation_id)">查看记录</button></article>
 <div class="button-row"><button :disabled="busy||page<=1" @click="page--;history()">上一页</button><span>第 {{page}} 页</span><button :disabled="busy||!more" @click="page++;history()">下一页</button></div>
 <p v-if="busy" role="status">正在处理…</p>
</section></template>
<style scoped>
.skill-points-maintenance{display:grid;gap:12px}.skill-points-maintenance form{display:grid;gap:12px}.skill-points-fields{display:grid;grid-template-columns:1fr 1fr;gap:16px}label{display:grid;gap:6px}.skill-points-preview{padding:16px;border:1px solid var(--border-color);border-radius:12px;background:var(--bg-secondary)}.button-row{display:flex;align-items:center;flex-wrap:wrap;gap:10px}article{display:flex;justify-content:space-between;align-items:center;gap:10px}p{overflow-wrap:anywhere}@media(max-width:600px){.skill-points-fields{grid-template-columns:1fr}}
</style>
