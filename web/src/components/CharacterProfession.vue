<script setup lang="ts">
import {ref,computed,onMounted,onBeforeUnmount,watch,nextTick} from 'vue'
import {api,ApiError,uncertainMessage} from '../api'
import {useGmConfirmation} from '../stores/gm/confirmation'
const confirmationLease=useGmConfirmation()
import {inventoryStates as states} from '../nativeStatus'
const props=defineProps<{characNo:number}>()
const emit=defineEmits(['busy','pending','reauth','expired','changed'])
const base='/character-profession',storage='dnfgm-character-profession-operation'
const current=ref<any>(null),operation=ref<any>(null),records=ref<any[]>([]),page=ref(1),more=ref(false)
const busy=ref(false),error=ref(''),reason=ref(''),reasonError=ref(''),valueError=ref(''),lookup=ref('')
const choice=ref(''),key=ref(''),attempted=ref(false),root=ref<HTMLElement|null>(null)
const unfinished=computed(()=>operation.value?.status==='preview'||operation.value?.status==='executing')
const pending=computed(()=>operation.value?.status==='executing'||attempted.value&&operation.value?.status==='preview')
let alive=true,timer:ReturnType<typeof setInterval>|undefined
watch(busy,v=>emit('busy',v));watch(unfinished,v=>emit('pending',v))
function failure(e:unknown){error.value=uncertainMessage(e);if(e instanceof ApiError&&e.status===401)emit('expired');if(e instanceof ApiError&&e.status===403&&e.message.includes('重新认证'))emit('reauth')}
function display(key:string,value:any){if(key!=='element_resist'||typeof value!=='string'||!/^[a-f0-9]{16}$/i.test(value))return value;const b=Uint8Array.from(value.match(/../g)!.map(x=>parseInt(x,16)));const view=new DataView(b.buffer);return ['火','水','暗','光'].map((name,i)=>name+' '+view.getInt16(i*2,true)).join(' / ')}
function remember(id:string){try{sessionStorage.setItem(storage,id)}catch{/* history lookup remains available */}}
async function run(fn:()=>Promise<void>){if(busy.value)return;busy.value=true;error.value='';try{await fn()}catch(e){if(alive)failure(e)}finally{if(alive)busy.value=false;if(operation.value?.status!=='preview')confirmationLease.release('character-characterprofession')}}
async function refresh(){await run(async()=>{const r=await api(`${base}/characters/${props.characNo}`);if(alive){current.value=r;choice.value=String(r.current.code)}})}
async function history(){await run(async()=>{const r=await api(`${base}/operations?charac_no=${props.characNo}&page=${page.value}`);if(alive){records.value=r.items;more.value=r.has_more}})}
function received(r:any){if(!alive)return;operation.value=r;remember(r.operation_id);if(r.status==='committed')emit('changed')}
async function inspect(id=operation.value?.operation_id){if(!id||!/^[a-f0-9]{32}$/.test(id)){error.value='请输入32位操作编号';return}await run(async()=>{received(await api(`${base}/operations/${id}`));attempted.value=true})}
async function preview(){
 if(busy.value||operation.value||!current.value)return
 reasonError.value=reason.value.trim()?'':'请填写操作原因';valueError.value=''
 const target=current.value.choices.find((o:any)=>String(o.code)===choice.value)
 if(!target)valueError.value='请选择列表中的目标转职／觉醒。'
 else if(target.code===current.value.current.code)valueError.value='目标职业阶段与当前相同，请选择其他阶段。'
 if(reasonError.value||valueError.value){await nextTick();root.value?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();return}
 if(!confirmationLease.acquire('character-characterprofession')){error.value='请先完成或关闭当前确认面板。';return}
 await run(async()=>{const r=await api(base+'/preview','POST',{action:'char-profession',uid:current.value.target.uid,charac_no:props.characNo,reference:current.value.reference,first:target.first,second:target.second,reason:reason.value.trim()});key.value=crypto.randomUUID().replaceAll('-','');attempted.value=false;received(r);await nextTick();root.value?.querySelector<HTMLElement>('.profession-preview')?.scrollIntoView?.({block:'nearest'})})
}
async function confirm(){if(!operation.value||attempted.value||!key.value)return;if(!confirmationLease.acquire('character-characterprofession')){error.value='请先完成或关闭当前确认面板。';return};attempted.value=true;await run(async()=>received(await api(`${base}/operations/${operation.value.operation_id}/confirm`,'POST',{idempotency_key:key.value})))}
async function cancel(){await run(async()=>received(await api(`${base}/operations/${operation.value.operation_id}/cancel-preview`,'POST',{})))}
async function finish(){operation.value=null;attempted.value=false;key.value='';try{sessionStorage.removeItem(storage)}catch{}await refresh();await history()}
onMounted(async()=>{await refresh();if(!alive)return;await history();if(!alive)return;let id='';try{id=sessionStorage.getItem(storage)||''}catch{}if(id)await inspect(id);timer=setInterval(()=>{if(alive&&pending.value&&!document.hidden&&!busy.value)void inspect()},10000)})
watch(()=>operation.value?.status,status=>{if(status==='preview')confirmationLease.acquire('character-characterprofession');else confirmationLease.release('character-characterprofession')})
onBeforeUnmount(()=>{confirmationLease.release('character-characterprofession');alive=false;if(timer)clearInterval(timer);emit('busy',false);emit('pending',false)})
</script>

<template><section ref="root" class="profession-maintenance">
 <div class="section-heading"><div><span class="eyebrow">PROFESSION</span><h3>转职／觉醒维护</h3></div><button :disabled="busy||unfinished" @click="refresh">刷新职业存档</button></div>
 <p class="field-hint">同基础职业内选择分支与觉醒，关联调整成长属性并重建两套PvE技能。不是只改职业编号，也不是在线原生转职。</p>
 <p v-if="error" class="submit-error" role="alert">{{error}}</p>
 <template v-if="current">
  <div class="profession-current"><div><small>当前角色</small><b>{{current.target.character.charac_name}} / #{{characNo}}</b><span>{{current.target.accountname}} / UID {{current.target.uid}}</span></div><div><small>基础职业（保持不变）</small><b>{{current.base_name}}</b><span>Lv.{{current.level}} · job {{current.job}}</span></div><div><small>当前转职／觉醒</small><b>{{current.current.name}}</b><span>{{current.current.branch}} · {{current.current.stage}}</span></div></div>
  <p class="notice">{{current.note}}</p>
  <p v-if="!current.enabled" class="warning">请在「功能与版本」开启「转职／觉醒维护」。</p>
  <p v-if="!current.maintenance.available" class="warning">{{current.maintenance.note}}</p>
  <form v-if="!operation" @submit.prevent="preview" novalidate>
   <label>目标转职／觉醒<select v-model="choice" :disabled="busy" :aria-invalid="!!valueError" aria-describedby="profession-choice-error"><option v-for="o in current.choices" :key="o.code" :value="String(o.code)">{{o.name}} · {{o.branch}} / {{o.stage}}{{o.code===current.current.code?'（当前）':''}}</option></select></label>
   <p v-if="valueError" id="profession-choice-error" class="submit-error" role="alert">{{valueError}}</p>
   <p class="field-hint">列表来自当前PVF；可退回未觉醒或切换同基础职业分支。装备、任务进度及QP保留，请自行检查目标职业适用性；不提供跨基础职业／性别变换。</p>
   <label>操作原因<input v-model="reason" :disabled="busy" maxlength="200" :aria-invalid="!!reasonError" aria-describedby="profession-reason-error" @input="reasonError=''" placeholder="例如：调整角色转职分支"></label>
   <p v-if="reasonError" id="profession-reason-error" class="submit-error" role="alert">{{reasonError}}</p>
   <button type="submit" class="primary" :disabled="busy||!current.enabled||!current.maintenance.available">预览职业、属性与技能变化</button>
  </form>
 </template>
 <section v-if="operation" class="profession-preview" tabindex="-1">
  <h4>{{states[operation.status]||operation.status}} · 转职／觉醒维护</h4>
  <p>目标：{{operation.preview.target.accountname}} / UID {{operation.preview.target.uid}} · {{operation.preview.target.character.charac_name}} / #{{operation.preview.target.character.charac_no}}</p>
  <div class="profession-transition"><div><small>修改前</small><b>{{operation.preview.profession_before?.name||'原始代码 '+operation.preview.before.info.grow_type}}</b></div><span aria-hidden="true">→</span><div><small>修改后</small><b>{{operation.preview.profession_after.name}}</b></div></div>
  <p class="warning">将重建两套PvE已学技能并重算基础SP／TP，人工额外赠点不保留；有效临时洗点备份同步重置。</p>
  <div class="profession-attributes"><article v-for="(c,k) in operation.preview.changes" :key="k"><small>{{(c as any).label}}</small><span>{{display(String(k),(c as any).before)}} → <b>{{display(String(k),(c as any).after)}}</b></span></article></div>
  <details v-for="c in operation.preview.skill_changes" :key="(c as any).tree"><summary>技能树{{(c as any).tree===0?'一':'二'}}：{{(c as any).before.skills.length}} → {{(c as any).after.skills.length}}个技能；SP {{(c as any).before.sp}} → {{(c as any).after.sp}}；TP {{(c as any).before.tp}} → {{(c as any).after.tp}}</summary><div class="profession-skills"><div><h5>修改前</h5><span v-for="s in (c as any).before.skills" :key="s.slot" class="skill-chip">{{s.name}} Lv.{{s.level}}</span></div><div><h5>重建后</h5><span v-for="s in (c as any).after.skills" :key="s.slot" class="skill-chip">{{s.name}} Lv.{{s.level}}</span></div></div><p v-if="(c as any).temporary_backup_reset" class="field-hint">该树临时洗点备份同步重置。</p><p v-for="s in (c as any).skipped_defaults" :key="s.skill_id" class="field-hint">#{{s.skill_id}}：{{s.reason}}</p></details>
  <p>原因：{{operation.preview.reason}}</p><p class="field-hint">操作编号：{{operation.operation_id}}</p>
  <p v-if="pending" class="notice">结果待确认，正在查询原编号，不会自动重复提交。</p>
  <p v-if="operation.status==='committed'" class="notice">职业、成长、技能存档与快照／审计已提交。结束维护后由游戏加载，不代表客户端效果已验证。</p>
  <div class="button-row"><button v-if="operation.status==='preview'&&!attempted&&key" class="danger" :disabled="busy" @click="confirm">确认修改转职／觉醒及关联存档</button><button :disabled="busy" @click="inspect()">查询原操作结果</button><button v-if="operation.status==='preview'&&!pending" :disabled="busy" @click="cancel">取消预览</button><button v-if="['committed','cancelled','aborted'].includes(operation.status)" :disabled="busy" @click="finish">结束查看</button></div>
 </section>
 <details><summary>职业维护历史与编号查询</summary><div class="button-row"><input v-model="lookup" aria-label="职业维护操作编号"><button :disabled="busy||!!operation" @click="inspect(lookup.trim())">查询职业维护操作</button></div><p v-if="!records.length">暂无职业维护记录</p><article v-for="r in records" :key="r.operation_id" class="history-row"><span>{{states[r.status]||r.status}} · {{r.preview.reason}}</span><button :disabled="busy||!!operation" @click="inspect(r.operation_id)">查看记录</button></article><div class="button-row"><button :disabled="busy||page<=1" @click="page--;history()">上一页</button><span>第 {{page}} 页</span><button :disabled="busy||!more" @click="page++;history()">下一页</button></div></details>
 <p v-if="busy" role="status">正在处理…</p>
</section></template>
<style scoped>
.profession-maintenance{display:grid;gap:14px}.section-heading,.button-row,.history-row{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap}.section-heading h3{margin:4px 0}.eyebrow{font-size:11px;letter-spacing:.12em;color:var(--text-secondary)}form,label{display:grid;gap:8px}form{gap:12px}.profession-current{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.profession-current>div,.profession-transition>div,.profession-attributes article{display:grid;gap:6px;padding:14px;border:1px solid var(--border-color);border-radius:10px;background:var(--bg-secondary)}small,.profession-current span{color:var(--text-secondary)}.profession-preview{display:grid;gap:12px;padding:16px;border:1px solid var(--border-color);border-radius:12px}.profession-transition{display:grid;grid-template-columns:1fr auto 1fr;gap:12px;align-items:center}.profession-attributes,.profession-skills{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.skill-chip{display:inline-block;padding:4px 8px;margin:3px;border:1px solid var(--border-color);border-radius:6px;font-size:12px}p,b,span{overflow-wrap:anywhere}select{width:100%;min-width:0}@media(max-width:650px){.profession-current,.profession-attributes,.profession-skills{grid-template-columns:1fr}.profession-transition{grid-template-columns:1fr}.profession-transition>span{justify-self:center;transform:rotate(90deg)}}
</style>
