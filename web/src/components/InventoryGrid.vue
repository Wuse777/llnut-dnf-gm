<script setup lang="ts">
import {computed,ref,watch,nextTick,onMounted,onUnmounted} from 'vue'
import GameImage from './GameImage.vue'
import ItemFacts from './ItemFacts.vue'
import Modal from './Modal.vue'
const emit=defineEmits<{manage:[item:any]}>()
const props=defineProps<{items:any[],slotCount:number,equipment?:boolean,filtered?:boolean,manageable?:boolean}>()
const page=ref(1),showEmpty=ref(true),selected=ref<any>(null),detail=ref<HTMLElement|null>(null)
let trigger:HTMLElement|null=null
const mobile=ref(false)
let media:MediaQueryList|null=null
function viewport(){mobile.value=media?.matches??false;void nextTick(()=>{if(selected.value&&!mobile.value)detail.value?.focus()})}
onMounted(()=>{if(typeof window.matchMedia==='function'){media=window.matchMedia('(max-width: 680px)');viewport();media.addEventListener('change',viewport)}})
onUnmounted(()=>media?.removeEventListener('change',viewport))
const names=['武器','称号','上衣','头肩','下装','鞋','腰带','项链','手镯','戒指','辅助装备','魔法石']
const slots=computed(()=>{
 if(!showEmpty.value||props.filtered)return props.items
 const n=Number.isInteger(props.slotCount)&&props.slotCount>=0&&props.slotCount<=1024?props.slotCount:0
 const map=new Map(props.items.map(i=>[i.slot,i]))
 return Array.from({length:n},(_,slot)=>map.get(slot)??{slot,empty:true,slot_label:props.equipment?names[slot]??'槽位 '+slot:'槽位 '+slot})
})
const pages=computed(()=>Math.max(1,Math.ceil(slots.value.length/30)))
const visible=computed(()=>slots.value.slice((page.value-1)*30,page.value*30))
const groups=computed(()=>{
 if(!props.equipment)return [{title:'',items:visible.value}]
 const parts=[{title:'武器与称号',slots:[0,1]},{title:'防具',slots:[2,3,4,5,6]},
  {title:'首饰',slots:[7,8,9]},{title:'特殊装备',slots:[10,11]}]
 const covered=new Set(parts.flatMap(p=>p.slots))
 return [...parts.map(p=>({title:p.title,items:visible.value.filter(i=>p.slots.includes(i.slot))})),
  {title:'其他存档槽位',items:visible.value.filter(i=>!covered.has(i.slot))}].filter(p=>p.items.length)
})
watch(()=>[props.items,props.slotCount,showEmpty.value,props.filtered],()=>{page.value=1;selected.value=null})
watch(page,()=>{selected.value=null})
function manage(){const item=selected.value;selected.value=null;emit('manage',item)}
async function select(item:any,e:Event){trigger=e.currentTarget as HTMLElement;selected.value=item;await nextTick();detail.value?.focus()}
function close(){selected.value=null;void nextTick(()=>{if(trigger?.isConnected)trigger.focus()})}
function number(v:unknown){return v===null||v===undefined?'未知':Number(v).toLocaleString('zh-CN')}
</script>
<template>
 <div class="inventory-visual">
  <label class="inventory-empty-toggle"><input v-model="showEmpty" type="checkbox" :disabled="filtered">显示空存档槽位<span v-if="filtered">（筛选期间隐藏）</span></label>
  <div class="inventory-layout">
   <div><div class="inventory-groups" :class="{'equipment-groups':equipment}" role="group" aria-label="存档物品槽位">
    <section v-for="group in groups" :key="group.title" class="inventory-slot-group" :aria-label="group.title||'背包与仓库槽位'">
     <h3 v-if="group.title" class="equipment-group-title">{{group.title}}<span>{{group.items.filter(i=>!i.empty).length}} / {{group.items.length}}</span></h3>
     <div class="inventory-slot-grid" :class="{'equipment-slot-grid':equipment}">
    <template v-for="i in group.items" :key="i.slot">
     <div v-if="i.empty" class="inventory-slot empty-slot"><small>{{i.slot_label}}</small><span>空</span><small>#{{i.slot}}</small></div>
     <button v-else type="button" class="inventory-slot" :class="{'slot-selected':selected?.slot===i.slot}" :aria-label="i.slot_label+'：'+i.name+'，数量'+number(i.quantity)" :aria-pressed="selected?.slot===i.slot" @click="select(i,$event)">
      <small>{{i.slot_label}}</small><GameImage :image="i.image" :label="i.name"/><b>{{i.name}}</b><small>×{{number(i.quantity)}}</small><span v-if="i.enhancement" class="slot-enhancement">+{{i.enhancement}}</span>
     </button>
    </template>
     </div>
    </section>
   </div><p v-if="!visible.length" class="empty">没有匹配的存档物品。</p>
   <div class="pagination"><button type="button" :disabled="page<=1" @click="page--">上一页槽位</button><span>{{page}} / {{pages}} · {{slots.length}} 槽</span><button type="button" :disabled="page>=pages" @click="page++">下一页槽位</button></div></div>
   <section v-if="selected&&!mobile" ref="detail" tabindex="-1" class="inventory-item-detail" role="region" aria-label="选中物品详情" data-escape-local @keydown.esc.stop="close">
    <div class="section-title"><h3>物品详情</h3><button type="button" @click="close">收起详情</button></div>
    <ItemFacts :item="selected" stored/><button v-if="manageable" type="button" @click="manage">维护此物品</button>
   </section>
  </div>
  <Teleport to="body"><Modal v-if="selected&&mobile" :title="'物品详情 · #'+selected.id" drawer @close="close"><ItemFacts :item="selected" stored/><template #footer><button type="button" @click="close">关闭物品详情</button><button v-if="manageable" type="button" class="primary" @click="manage">维护此物品</button></template></Modal></Teleport>
 </div>
</template>

<style scoped>
.inventory-groups{display:grid;gap:18px}.equipment-groups{grid-template-columns:repeat(2,minmax(0,1fr));align-items:start}.inventory-slot-group{min-width:0}.equipment-group-title{display:flex;justify-content:space-between;gap:8px;padding:0 0 9px;margin:0 0 10px;border-bottom:1px solid var(--border-color);font-size:12px;color:var(--text-secondary)}.equipment-group-title span{font-size:10px;font-variant-numeric:tabular-nums;color:var(--text-tertiary)}.equipment-slot-grid{grid-template-columns:repeat(auto-fit,minmax(85px,1fr))}.equipment-groups .empty-slot{border-style:dashed;min-height:125px}.inventory-slot b{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.inventory-slot:focus-visible{outline:2px solid var(--primary-color);outline-offset:2px}.inventory-item-detail{position:sticky;top:8px}
@media(max-width:680px){.equipment-groups{grid-template-columns:minmax(0,1fr);gap:18px}.equipment-slot-grid{grid-template-columns:repeat(3,minmax(0,1fr))}.equipment-groups .inventory-slot{min-height:118px}.equipment-groups .inventory-slot b{font-size:11px}.equipment-group-title{font-size:12px}}
</style>
