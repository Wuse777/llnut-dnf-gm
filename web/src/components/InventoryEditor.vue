<script setup lang="ts">
import {computed,onMounted,onBeforeUnmount,nextTick,ref,watch} from 'vue'
import {api,ApiError,uncertainMessage} from '../api'
import {useGmConfirmation} from '../stores/gm/confirmation'
const confirmationLease=useGmConfirmation()
import {inventoryNames as names,inventoryStates as states} from '../nativeStatus'
import ItemCard from './ItemCard.vue'
import EnchantmentPicker from './EnchantmentPicker.vue'
import EquipmentComparison from './EquipmentComparison.vue'
const props=defineProps<{characNo:number,selection?:{container:string,slot:number}|null}>()
const emit=defineEmits(['busy','pending','reauth','expired','changed'])
const item=ref<any>(null),detail=ref<any>(null),history=ref<any[]>([]),page=ref(1),more=ref(false)
const busy=ref(false),historyBusy=ref(false),error=ref(''),fields=ref<Record<string,string>>({}),reason=ref(''),action=ref('item-edit')
const values=ref<Record<string,string>>({}),source=ref(''),key=ref(''),attempted=ref(false),lookup=ref('')
const storage='dnfgm-inventory-operation'
const root=ref<HTMLElement|null>(null)
const containerNames:Record<string,string>={inventory:'角色背包',equipment:'穿戴装备',warehouse:'角色仓库',account_warehouse:'账号仓库'}
const fieldName=(k:string)=>labels[k]||({id:'物品编号',empty:'空槽位'} as Record<string,string>)[k]||k
const display=(v:unknown)=>typeof v==='boolean'?(v?'是':'否'):String(v??'—')
const differences=computed(()=>{const p=detail.value?.preview;if(!p)return [];return [...new Set([...Object.keys(p.before),...Object.keys(p.after)])].filter(k=>(labels[k]||['id','empty'].includes(k))&&p.before[k]!==p.after[k]).map(k=>({key:k,before:p.before[k],after:p.after[k]}))})
async function focusResult(){await nextTick();root.value?.querySelector<HTMLElement>('.inventory-change-preview')?.scrollIntoView?.({block:'start'})}
const labels:Record<string,string>={enhancement:'强化',forge:'锻造',durability:'耐久',amplify_type:'增幅类型代码',amplify_value:'增幅数值',orb_id:'附魔物品 ID',quality_raw:'原始品级（不是百分比）',quantity:'数量'}
const max:Record<string,number>={enhancement:31,forge:255,durability:65535,amplify_type:4,amplify_value:65535,orb_id:4294967295,quality_raw:4294967295,quantity:2147483647}
const pending=computed(()=>detail.value?.status==='executing'||(attempted.value&&detail.value?.status==='preview'))
const unfinished=computed(()=>detail.value?.status==='preview'||pending.value)
const editable=computed(()=>Object.keys(labels).filter(k=>item.value?.item?.[k]!==undefined))
const fieldGroups=computed(()=>[
 {title:'强化与锻造',keys:['enhancement','forge']},
 {title:'增幅',keys:['amplify_type','amplify_value']},
 {title:'耐久与数量',keys:['durability','quantity']},
].map(g=>({...g,keys:g.keys.filter(k=>editable.value.includes(k))})).filter(g=>g.keys.length))
const slotReason=computed(()=>action.value==='item-restore'?'':item.value?.item?.empty?'当前槽位为空，不能编辑或回收':item.value?.item?.editable===false?(item.value.item.unsupported_reason||'当前物品类型尚未适配'):action.value==='item-reclaim'&&item.value?.item?.lock_key?'请先完成装备解锁，再回收此物品':'')
const allowed=computed(()=>!slotReason.value&&item.value?.maintenance?.available&&item.value?.reference&&item.value?.enabled_actions?.includes(action.value))
let alive=true,epoch=0,timer:ReturnType<typeof setInterval>|undefined
watch(busy,v=>emit('busy',v));watch(unfinished,v=>emit('pending',v))
function remember(id:string){try{sessionStorage.setItem(storage,id)}catch{/* History still permits manual lookup. */}}
function fail(e:unknown){error.value=uncertainMessage(e);if(e instanceof ApiError&&e.status===401)emit('expired');if(e instanceof ApiError&&e.status===403&&e.message.includes('重新认证'))emit('reauth')}
async function historyLoad(){if(historyBusy.value)return;const n=++epoch;historyBusy.value=true;try{const r=await api(`/inventory/operations?charac_no=${props.characNo}&page=${page.value}`);if(alive&&n===epoch){history.value=r.items;more.value=r.has_more}}catch(e){if(alive)fail(e)}finally{if(alive)historyBusy.value=false}}
async function loadSlot(container:string,slot:number,restore=''){
 if(busy.value||pending.value||detail.value?.status==='preview'){error.value='请先查询或取消原操作，不能覆盖未完成的预览';return}
 busy.value=true;error.value='';fields.value={};item.value=null;detail.value=null;attempted.value=false;key.value='';source.value=restore
 try{const r=await api(`/inventory/characters/${props.characNo}/${container}/${slot}`);if(!alive)return;item.value=r;action.value=restore?'item-restore':'item-edit';values.value=Object.fromEntries(Object.keys(labels).filter(k=>r.item[k]!==undefined).map(k=>[k,String(r.item[k])]))}
 catch(e){if(alive)fail(e)}finally{if(alive)busy.value=false}
}
async function inspect(id=detail.value?.operation_id){
 if(busy.value||!id)return;if(!/^[a-f0-9]{32}$/.test(id)){error.value='请输入32位操作编号';return}
 const fresh=id===detail.value?.operation_id&&!!key.value&&!attempted.value
 busy.value=true;error.value=''
 try{const r=await api('/inventory/operations/'+id);if(!alive)return;const wasCommitted=detail.value?.operation_id===id&&detail.value?.status==='committed';detail.value=r;attempted.value=!fresh;remember(id);if(r.status==='committed'&&!wasCommitted)emit('changed')}catch(e){if(alive)fail(e)}finally{if(alive)busy.value=false}
}
async function prepare(){
 if(busy.value||detail.value||!item.value)return;fields.value={};error.value=''
 if(!reason.value.trim())fields.value.reason='请填写操作原因'
 if(!allowed.value)fields.value.window='该操作未激活或没有可验证的维护窗口'
 const changes:Record<string,number>={}
 if(action.value==='item-edit')for(const k of editable.value){const text=values.value[k]?.trim()??'',value=Number(text);if(!/^\d+$/.test(text)||!Number.isSafeInteger(value)||value<(k==='quantity'?1:0)||value>max[k])fields.value[k]=`请输入${k==='quantity'?1:0}–${max[k]}的整数`;else if(value!==item.value.item[k])changes[k]=value}
 if(action.value==='item-edit'&&!Object.keys(changes).length)fields.value.changes='请至少修改一个属性'
 if(values.value.amplify_type==='0'&&Number(values.value.amplify_value)>0&&action.value==='item-edit')fields.value.amplify_value='类型为0时，增幅数值必须同时为0'
 if(Object.keys(fields.value).length){await nextTick();const invalid=root.value?.querySelector<HTMLElement>('[aria-invalid="true"]');const fold=invalid?.closest('details');if(fold)fold.open=true;invalid?.focus();invalid?.scrollIntoView?.({block:'center'});return}
 if(!confirmationLease.acquire('inventory')){error.value='请先完成或关闭当前确认面板。';return}
 busy.value=true
 try{const r=await api('/inventory/preview','POST',{action:action.value,uid:item.value.uid,charac_no:item.value.charac_no,container:item.value.container,slot:item.value.slot,reference:item.value.reference,changes,source_operation_id:source.value||null,reason:reason.value.trim()});if(!alive)return;detail.value=r;key.value=crypto.randomUUID();attempted.value=false;remember(r.operation_id);void focusResult()}catch(e){if(alive)fail(e)}finally{if(alive)busy.value=false}
}
async function confirm(){
 if(busy.value||attempted.value||!key.value||detail.value?.status!=='preview')return
 if(!confirmationLease.acquire('inventory')){error.value='请先完成或关闭当前确认面板。';return}
 attempted.value=true;remember(detail.value.operation_id);busy.value=true;error.value=''
 try{const r=await api('/inventory/operations/'+detail.value.operation_id+'/confirm','POST',{idempotency_key:key.value});if(!alive)return;detail.value=r;if(r.status==='committed')emit('changed');void historyLoad()}
 catch(e){if(alive){fail(e);error.value+='；请只查询原操作编号，不要重新确认。'}}finally{if(alive)busy.value=false}
}
async function cancel(){if(busy.value||detail.value?.status!=='preview')return;busy.value=true;error.value='';try{const r=await api('/inventory/operations/'+detail.value.operation_id+'/cancel-preview','POST');if(alive){detail.value=r;void historyLoad()}}catch(e){if(alive)fail(e)}finally{if(alive)busy.value=false}}
function reset(){if(busy.value||pending.value||detail.value?.status==='preview')return;detail.value=null;attempted.value=false;key.value='';try{sessionStorage.removeItem(storage)}catch{};if(item.value)void loadSlot(item.value.container,item.value.slot)}
async function restore(row:any){if(detail.value||busy.value){error.value='请先结束当前操作查看';return}const r=row.request;await loadSlot(r.container,r.slot,row.operation_id)}
watch(()=>props.selection,(s)=>{if(s)void loadSlot(s.container,s.slot)})
onMounted(async()=>{void historyLoad();let id='';try{id=sessionStorage.getItem(storage)||''}catch{};if(/^[a-f0-9]{32}$/.test(id))await inspect(id);else if(props.selection)await loadSlot(props.selection.container,props.selection.slot);timer=setInterval(()=>{if(!document.hidden&&pending.value&&!busy.value)void inspect()},10000)})
watch(()=>detail.value?.status,status=>{if(status==='preview')confirmationLease.acquire('inventory');else confirmationLease.release('inventory')})
watch(busy,value=>{if(!value&&detail.value?.status!=='preview')confirmationLease.release('inventory')})
onBeforeUnmount(()=>{confirmationLease.release('inventory');alive=false;epoch++;if(timer)clearInterval(timer);emit('busy',false);emit('pending',false)})
</script>
<template><section ref="root" class="inventory-editor" aria-label="装备存档维护">
 <h3>装备与道具维护</h3><p class="field-hint">请先在“维护中心”申请并核对保留 MySQL 的维护窗口。此页面不会自动停服；账号离线不等于可以安全修改存档。</p>
 <p v-if="error" class="submit-error" role="alert">{{error}}</p>
 <template v-if="!detail">
  <p v-if="!item" class="empty">从穿戴、背包或仓库选择“维护此物品”；也可查看下方历史记录。</p>
  <form v-else class="inventory-edit-form" @submit.prevent="prepare">
   <div class="inventory-edit-target"><strong>{{item.target.accountname}} · UID {{item.uid}}</strong><p>{{item.target.character.charac_name}} · 角色 #{{item.charac_no}} · {{containerNames[item.container]||item.container}} / 槽位 {{item.slot}}</p><ItemCard :item="item.item" stored/><p class="field-hint">{{item.item.part_name||item.item.type_name||'类型未收录'}}<template v-if="item.item.level!=null"> · Lv. {{item.item.level}}</template> · {{item.item.slot_label||'槽位 '+item.slot}}</p></div>
   <p class="notice" role="status">{{item.maintenance.available?'维护窗口已核验；提交时仍会重新检查':'维护窗口不可用，当前只能查看，不能生成写入预览'}}</p>
   <p v-if="slotReason" class="notice" role="status">{{slotReason}}</p>
   <label>操作<select v-model="action" :disabled="busy||!!source" aria-label="装备维护操作"><option value="item-edit">修改存档属性</option><option value="item-reclaim">回收此槽位物品</option><option v-if="source" value="item-restore">恢复历史快照</option></select></label>
   <p v-if="action==='item-reclaim'" class="submit-error">将清空这个槽位，不是撤回邮件。锁定或关联类型会被拒绝；请仔细核对目标。</p>
   <p v-if="source" class="field-hint">恢复来源：{{source}}。只有整个当前容器仍与原操作后完全一致时才能恢复。</p>
   <template v-if="action==='item-edit'">
    <section v-for="group in fieldGroups" :key="group.title" class="equipment-control-group"><h4>{{group.title}}</h4><div class="inventory-edit-fields"><label v-for="k in group.keys" :key="k">{{labels[k]}}<select v-if="k==='amplify_type'" v-model="values[k]" :aria-label="labels[k]" :aria-invalid="!!fields[k]" :disabled="busy"><option value="0">0 · 无增幅类型</option><option v-for="code in 4" :key="code" :value="String(code)">{{code}} · 类型代码 {{code}}</option></select><input v-else v-model="values[k]" inputmode="numeric" :aria-label="labels[k]" :aria-invalid="!!fields[k]" :disabled="busy"><small v-if="fields[k]" class="field-error" role="alert">{{fields[k]}}</small><small class="field-hint">当前 {{item.item[k]}}<template v-if="k==='durability'&&item.item.base_durability!=null"> · PVF基础耐久 {{item.item.base_durability}}</template></small></label></div><p v-if="group.title==='增幅'" class="field-hint">类型仍按代码展示，不猜测对应属性；类型为0时，增幅数值必须同时为0。</p></section>
    <template v-if="editable.includes('orb_id')"><EnchantmentPicker v-model="values.orb_id" :current="item.item.enchantment" :disabled="busy" @error="fail"/><label>附魔物品 ID<input v-model="values.orb_id" inputmode="numeric" aria-label="附魔物品 ID" :aria-invalid="!!fields.orb_id" :disabled="busy"><small v-if="fields.orb_id" class="field-error" role="alert">{{fields.orb_id}}</small><small class="field-hint">可从上方选择，也可手动填写；0表示清除附魔，确认前会显示识别名称。</small></label></template>
    <details v-if="editable.includes('quality_raw')" class="equipment-advanced"><summary>高级原始字段 · 品级</summary><label>{{labels.quality_raw}}<input v-model="values.quality_raw" inputmode="numeric" :aria-label="labels.quality_raw" :aria-invalid="!!fields.quality_raw" :disabled="busy"><small v-if="fields.quality_raw" class="field-error" role="alert">{{fields.quality_raw}}</small></label><p class="field-hint">存档原始32位数值，不是0–100%的装备品级。</p></details>
   </template>
   <p v-if="action==='item-edit'" class="field-hint">强化、增幅等是存档字段；原始品级不是百分比。附魔 ID 可检索不代表适用于当前装备。数量不按 PVF 堆叠上限限制。</p>
   <label>操作原因<input v-model="reason" maxlength="200" aria-label="装备维护原因" :aria-invalid="!!fields.reason" :disabled="busy" placeholder="例如：纠正测试装备属性"><small v-if="fields.reason" class="field-error" role="alert">{{fields.reason}}</small></label>
   <p v-if="fields.window||fields.changes" class="submit-error" role="alert">{{fields.window||fields.changes}}</p>
   <button class="primary" :disabled="busy||!allowed">生成装备操作预览</button><p v-if="!item.enabled_actions?.includes(action)" class="field-hint">该装备写入能力尚未激活。</p>
  </form>
 </template>
 <section v-else class="inventory-change-preview" aria-label="装备操作预览与结果">
  <p v-if="detail.preview.target.character.charac_no!==characNo" class="notice" role="status">正在核对角色 #{{detail.preview.target.character.charac_no}} 的原操作，不是当前打开的角色 #{{characNo}}。原操作不会改投其他角色；结束查看后再选择当前角色物品。</p>
  <h4>{{names[detail.action]}} · {{states[detail.status]||'未知状态'}}</h4>
  <p>{{detail.preview.target.accountname}} · UID {{detail.preview.target.uid}} · {{detail.preview.target.character.charac_name}} / #{{detail.preview.target.character.charac_no}}</p>
  <p>{{containerNames[detail.preview.container]||detail.preview.container}} / 槽位 {{detail.preview.slot}} · {{detail.preview.item_name}}</p><p class="operation-number">操作编号：{{detail.operation_id}}</p>
  <p>原因：{{detail.preview.reason}}</p>
  <EquipmentComparison :preview="detail.preview" :current-item="item?.item"/>
  <div class="inventory-diff" aria-label="本次变更"><h4>本次变更</h4><div v-for="d in differences" :key="d.key"><b>{{fieldName(d.key)}}</b><span>{{display(d.before)}} → <strong>{{display(d.after)}}</strong></span></div></div>
  <details><summary>查看完整修改前后存档字段</summary><div class="inventory-before-after"><div><h4>修改前</h4><dl><template v-for="(v,k) in detail.preview.before" :key="k"><template v-if="labels[String(k)]||k==='id'||k==='empty'"><dt>{{fieldName(String(k))}}</dt><dd>{{display(v)}}</dd></template></template></dl></div><div><h4>修改后</h4><dl><template v-for="(v,k) in detail.preview.after" :key="k"><template v-if="labels[String(k)]||k==='id'||k==='empty'"><dt>{{fieldName(String(k))}}</dt><dd>{{display(v)}}</dd></template></template></dl></div></div></details>
  <p v-if="pending" class="notice" role="status">结果待核对。只查询原编号，不自动重放。执行意向未解决时，维护者关闭窗口会等待数据库事务并核对结果。</p>
  <p v-if="detail.status==='committed'" class="notice">数据库修改、快照和成功审计已提交；游戏内效果仍未由此证明。</p>
  <p v-if="detail.status==='aborted'" class="notice">维护者核对后确认本操作没有提交游戏事务。如仍需修改，请在新维护窗口重新读取并预览。</p>
  <div class="button-row"><button v-if="detail.status==='preview'&&!attempted&&key" class="danger" :disabled="busy" @click="confirm">确认执行装备操作</button><button :disabled="busy" @click="inspect()">查询原操作结果</button><button v-if="detail.status==='preview'" :disabled="busy" @click="cancel">取消原预览</button><button v-if="['committed','cancelled','aborted'].includes(detail.status)" :disabled="busy" @click="reset">结束查看</button></div>
 </section>
 <details><summary>按操作编号查询</summary><div class="toolbar"><input v-model="lookup" aria-label="装备操作编号"><button :disabled="busy||!!detail" @click="inspect(lookup.trim())">查询装备操作</button></div></details>
 <section class="inventory-edit-history"><div class="section-title"><h4>角色装备维护历史</h4><button :disabled="busy||historyBusy" @click="historyLoad">刷新维护记录</button></div><p v-if="!history.length" class="empty">暂无记录</p><article v-for="r in history" :key="r.operation_id"><p><b>{{names[r.action]}}</b> · {{r.preview.item_name}} · {{containerNames[r.preview.container]||r.preview.container}} / 槽位 {{r.preview.slot}}</p><p>{{states[r.status]||'未知状态'}} · {{r.preview.reason}}</p><div class="button-row"><button :disabled="busy||!!detail" @click="inspect(r.operation_id)">查看记录</button><button v-if="r.status==='committed'&&r.result?.snapshot_id" :disabled="busy||!!detail" @click="restore(r)">创建恢复预览</button></div></article><div class="pagination"><button :disabled="busy||historyBusy||page<=1" @click="page--;historyLoad()">上一页维护记录</button><span>第 {{page}} 页</span><button :disabled="busy||historyBusy||!more" @click="page++;historyLoad()">下一页维护记录</button></div></section>
 <p v-if="busy" role="status">正在处理，请勿重复操作…</p>
</section></template>
<style scoped>
.equipment-control-group{padding:16px;border:1px solid var(--border-color);border-radius:12px}.equipment-control-group h4{margin:0 0 12px}.equipment-advanced{padding:12px;border:1px dashed var(--border-color);border-radius:10px}.equipment-advanced label{display:grid;gap:6px;margin-top:12px}.inventory-edit-target :deep(.item-name-row){margin-top:12px}.inventory-diff{padding:14px;border:1px solid var(--border-color);border-radius:10px;background:var(--bg-secondary)}.inventory-diff>div{display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px;padding:6px 0}.inventory-diff h4{margin:0 0 8px}.inventory-edit-form{display:grid;gap:14px}.inventory-edit-form>label{display:grid;gap:6px}.inventory-edit-fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.inventory-edit-fields label{display:grid;gap:6px}.inventory-edit-target{padding:16px;border:1px solid var(--border-color);border-radius:12px}.inventory-editor .operation-number{overflow-wrap:anywhere}.inventory-editor .button-row{display:flex;flex-wrap:wrap;gap:10px;margin:12px 0}.inventory-before-after{display:grid;grid-template-columns:1fr 1fr;gap:16px}.inventory-before-after>div{padding:12px;background:var(--bg-secondary);border:1px solid var(--border-color);border-radius:10px}.inventory-before-after dl{display:grid;grid-template-columns:1fr auto;gap:8px}.inventory-before-after dd{margin:0}.inventory-edit-history{margin-top:24px}.inventory-edit-history article{padding:12px 0;border-bottom:1px solid var(--border-color)}.inventory-editor details{margin:18px 0}.inventory-editor p{overflow-wrap:anywhere}@media(max-width:600px){.inventory-edit-fields,.inventory-before-after{grid-template-columns:1fr}.inventory-editor .button-row>button{flex:1 1 140px}}
</style>
