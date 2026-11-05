<script setup lang="ts">
import {ref,computed,onMounted,onBeforeUnmount,watch,nextTick} from 'vue'
import {api,ApiError,uncertainMessage} from '../api'
import {inventoryStates as states} from '../nativeStatus'
const props=defineProps<{characNo:number}>()
const emit=defineEmits(['busy','pending','reauth','expired','changed'])
const base='/character-levels',storage='dnfgm-character-level-operation'
const current=ref<any>(null),operation=ref<any>(null),records=ref<any[]>([]),page=ref(1),more=ref(false)
const busy=ref(false),error=ref(''),reason=ref(''),reasonError=ref(''),valueError=ref(''),lookup=ref('')
const level=ref(''),experience=ref(''),key=ref(''),attempted=ref(false),root=ref<HTMLElement|null>(null)
const unfinished=computed(()=>operation.value?.status==='preview'||operation.value?.status==='executing')
const pending=computed(()=>operation.value?.status==='executing'||attempted.value&&operation.value?.status==='preview')
const labels=computed<Record<string,string>>(()=>current.value?.labels||{})
let alive=true,timer:ReturnType<typeof setInterval>|undefined
watch(busy,v=>emit('busy',v));watch(unfinished,v=>emit('pending',v))
function failure(e:unknown){error.value=uncertainMessage(e);if(e instanceof ApiError&&e.status===401)emit('expired');if(e instanceof ApiError&&e.status===403&&e.message.includes('重新认证'))emit('reauth')}
function display(key:string,value:any){if(key!=='element_resist'||typeof value!=='string'||!/^[a-f0-9]{16}$/i.test(value))return value;const b=Uint8Array.from(value.match(/../g)!.map(x=>parseInt(x,16)));const view=new DataView(b.buffer);return ['火','水','暗','光'].map((name,i)=>name+' '+view.getInt16(i*2,true)).join(' / ')}
function remember(id:string){try{sessionStorage.setItem(storage,id)}catch{/* history lookup remains available */}}
async function run(fn:()=>Promise<void>){if(busy.value)return;busy.value=true;error.value='';try{await fn()}catch(e){if(alive)failure(e)}finally{if(alive)busy.value=false}}
async function refresh(){await run(async()=>{const r=await api(`${base}/characters/${props.characNo}`);if(alive){current.value=r;level.value=String(r.archive.info.lev);experience.value=''}})}
async function history(){await run(async()=>{const r=await api(`${base}/operations?charac_no=${props.characNo}&page=${page.value}`);if(alive){records.value=r.items;more.value=r.has_more}})}
function received(r:any){if(!alive)return;operation.value=r;remember(r.operation_id);if(r.status==='committed')emit('changed')}
async function inspect(id=operation.value?.operation_id){if(!id||!/^[a-f0-9]{32}$/.test(id)){error.value='请输入32位操作编号';return}await run(async()=>{received(await api(`${base}/operations/${id}`));attempted.value=true})}
async function preview(){
 if(busy.value||operation.value||!current.value)return
 reasonError.value=reason.value.trim()?'':'请填写操作原因';valueError.value=''
 if(!current.value.levels.some((r:any)=>r.level===Number(level.value)))valueError.value='请选择有匹配成长和经验规则的目标等级。'
 if(experience.value.trim()&&(!/^\d+$/.test(experience.value)||Number(experience.value)>4294967295))valueError.value='经验须为0至4294967295的整数；留空使用目标等级起点。'
 if(reasonError.value||valueError.value){await nextTick();root.value?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();return}
 await run(async()=>{const r=await api(base+'/preview','POST',{action:'char-level',uid:current.value.target.uid,charac_no:props.characNo,reference:current.value.reference,level:Number(level.value),experience:experience.value.trim()?Number(experience.value):null,reason:reason.value.trim()});key.value=crypto.randomUUID().replaceAll('-','');attempted.value=false;received(r);await nextTick();root.value?.querySelector<HTMLElement>('.level-preview')?.scrollIntoView?.({block:'nearest'})})
}
async function confirm(){if(!operation.value||attempted.value||!key.value)return;attempted.value=true;await run(async()=>received(await api(`${base}/operations/${operation.value.operation_id}/confirm`,'POST',{idempotency_key:key.value})))}
async function cancel(){await run(async()=>received(await api(`${base}/operations/${operation.value.operation_id}/cancel-preview`,'POST',{})))}
async function finish(){operation.value=null;attempted.value=false;key.value='';try{sessionStorage.removeItem(storage)}catch{}await refresh();await history()}
onMounted(async()=>{await refresh();if(!alive)return;await history();if(!alive)return;let id='';try{id=sessionStorage.getItem(storage)||''}catch{}if(id)await inspect(id);timer=setInterval(()=>{if(alive&&pending.value&&!document.hidden&&!busy.value)void inspect()},10000)})
onBeforeUnmount(()=>{alive=false;if(timer)clearInterval(timer);emit('busy',false);emit('pending',false)})
</script>
<template><section ref="root" class="level-maintenance">
 <header><div><span class="pill">存档维护</span><h3>调整等级与经验</h3></div><button :disabled="busy||unfinished" @click="refresh">刷新关联存档</button></header>
 <p v-if="error" class="submit-error" role="alert">{{error}}</p>
 <template v-if="current">
  <p class="notice">{{current.note}} 请在「维护中心」显式开启维护窗口；打开本页不会停服。</p>
  <div class="level-target"><b>{{current.target.character.charac_name}}</b><span>{{current.target.accountname}} · UID {{current.target.uid}} · 角色 #{{characNo}}</span><strong>Lv. {{current.archive.info.lev}}</strong></div>
  <p v-if="!current.enabled" class="warning">请在「功能与权限」开启「等级／经验维护」。无需SSH，开启后适用于全部账号。</p>
  <p v-if="!current.maintenance.available" class="warning">{{current.maintenance.note}}</p>
  <form v-if="!operation" @submit.prevent="preview" novalidate>
   <div class="level-fields"><label>目标等级<select v-model="level" :disabled="busy" :aria-invalid="!!valueError" aria-describedby="level-value-error"><option v-for="v in current.levels" :key="v.level" :value="String(v.level)">Lv. {{v.level}} · 起点经验 {{v.experience.toLocaleString('zh-CN')}}</option></select></label><label>目标累计经验（可选）<input v-model="experience" inputmode="numeric" :disabled="busy" :aria-invalid="!!valueError" aria-describedby="level-value-error" placeholder="留空：使用目标等级起点"><small>保持当前等级也可核对并同步两处经验。负的数据库原值以无符号经验填写。</small></label></div>
   <p v-if="valueError" id="level-value-error" class="submit-error" role="alert">{{valueError}}</p>
   <label>操作原因<input v-model="reason" :disabled="busy" maxlength="200" :aria-invalid="!!reasonError" aria-describedby="level-reason-error" @input="reasonError=''" placeholder="例如：活动等级奖励或修正经验存档"></label>
   <p v-if="reasonError" id="level-reason-error" class="submit-error" role="alert">{{reasonError}}</p>
   <p class="field-hint">{{current.point_rule}}</p>
   <button class="primary" :disabled="busy||!current.enabled||!current.maintenance.available" type="submit">预览等级、成长与技能点变化</button>
  </form>
 </template>
 <section v-if="operation" class="level-preview">
  <h4>{{states[operation.status]||operation.status}}</h4>
  <p>目标：{{operation.preview.target.accountname}} / UID {{operation.preview.target.uid}} · {{operation.preview.target.character.charac_name}} / #{{operation.preview.target.character.charac_no}}</p>
  <p>操作编号：{{operation.operation_id}}</p><p>原因：{{operation.preview.reason}}</p>
  <div class="level-changes"><article v-for="(v,k) in operation.preview.changes" :key="k"><span>{{labels[String(k)]||k}}</span><div><del>{{display(String(k),(v as any).before)}}</del><span aria-hidden="true"> → </span><strong>{{display(String(k),(v as any).after)}}</strong></div></article></div>
  <p class="field-hint">属性显示数据库存档单位，部分为十分之一单位，不是客户端面板属性；元素抗性按火／水／暗／光解码显示。职业、装备、任务、已学技能不变。</p>
  <p v-if="pending" class="notice">结果待核对，正在查询原操作编号。不会自动重复提交。</p>
  <p v-if="operation.status==='committed'" class="notice">关联存档、快照与审计已提交。结束维护后由游戏加载；这不等于客户端效果已验证。</p>
  <div class="button-row"><button v-if="operation.status==='preview'&&!attempted&&key" class="danger" :disabled="busy" @click="confirm">确认修改等级与关联存档</button><button :disabled="busy" @click="inspect()">查询原操作结果</button><button v-if="operation.status==='preview'&&!pending" :disabled="busy" @click="cancel">取消预览</button><button v-if="['committed','cancelled','aborted'].includes(operation.status)" :disabled="busy" @click="finish">结束查看</button></div>
 </section>
 <details><summary>按操作编号查询</summary><input v-model="lookup" aria-label="等级维护操作编号"><button :disabled="busy||!!operation" @click="inspect(lookup.trim())">查询等级维护操作</button></details>
 <h4>等级维护历史</h4><p v-if="!records.length">暂无记录</p>
 <article v-for="r in records" :key="r.operation_id" class="level-history"><span>{{states[r.status]||r.status}} · {{r.preview.reason}}</span><button :disabled="busy||!!operation" @click="inspect(r.operation_id)">查看记录</button></article>
 <div class="button-row"><button :disabled="busy||page<=1" @click="page--;history()">上一页</button><span>第 {{page}} 页</span><button :disabled="busy||!more" @click="page++;history()">下一页</button></div>
 <p v-if="busy" role="status">正在处理…</p>
</section></template>
<style scoped>
.level-maintenance{display:grid;gap:14px;border-top:1px solid var(--border-color);margin-top:22px;padding-top:22px}.level-maintenance header,.level-target,.button-row,.level-history{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.level-maintenance h3{margin:8px 0}.level-target{padding:16px;border:1px solid var(--border-color);border-radius:12px;background:var(--bg-secondary)}.level-target strong{font-size:24px;color:var(--primary-color)}.level-maintenance form,.level-maintenance label{display:grid;gap:10px}.level-fields,.level-changes{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.level-preview{padding:16px;border:1px solid var(--border-color);border-radius:12px;background:var(--bg-secondary)}.level-changes article{display:grid;gap:8px;padding:12px;border:1px solid var(--border-color);border-radius:10px}.level-changes del{opacity:.65}.level-maintenance p,.level-changes article{overflow-wrap:anywhere}.button-row{justify-content:flex-start}label,select,input{min-width:0;max-width:100%}@media(max-width:600px){.level-fields,.level-changes{grid-template-columns:1fr}}
</style>
