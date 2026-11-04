<script setup lang="ts">
import {computed,ref,watch,nextTick} from 'vue'
import GameImage from './GameImage.vue'
const props=defineProps<{items:any[],slotCount:number,equipment?:boolean,filtered?:boolean}>()
const page=ref(1),showEmpty=ref(true),selected=ref<any>(null),detail=ref<HTMLElement|null>(null)
let trigger:HTMLElement|null=null
const names=['武器','称号','上衣','头肩','下装','鞋','腰带','项链','手镯','戒指','辅助装备','魔法石']
const slots=computed(()=>{
 if(!showEmpty.value||props.filtered)return props.items
 const n=Number.isInteger(props.slotCount)&&props.slotCount>=0&&props.slotCount<=1024?props.slotCount:0
 const map=new Map(props.items.map(i=>[i.slot,i]))
 return Array.from({length:n},(_,slot)=>map.get(slot)??{slot,empty:true,slot_label:props.equipment?names[slot]??'槽位 '+slot:'槽位 '+slot})
})
const pages=computed(()=>Math.max(1,Math.ceil(slots.value.length/30)))
const visible=computed(()=>slots.value.slice((page.value-1)*30,page.value*30))
watch(()=>[props.items,props.slotCount,showEmpty.value],()=>{page.value=1;selected.value=null})
async function select(item:any,e:Event){trigger=e.currentTarget as HTMLElement;selected.value=item;await nextTick();detail.value?.focus()}
function close(){selected.value=null;void nextTick(()=>{if(trigger?.isConnected)trigger.focus()})}
function number(v:unknown){return v===null||v===undefined?'未知':Number(v).toLocaleString('zh-CN')}
</script>
<template>
 <div class="inventory-visual">
  <label class="inventory-empty-toggle"><input v-model="showEmpty" type="checkbox" :disabled="filtered">显示空存档槽位<span v-if="filtered">（筛选期间隐藏）</span></label>
  <div class="inventory-layout">
   <div><div class="inventory-slot-grid" :class="{'equipment-slot-grid':equipment}" role="group" aria-label="存档物品槽位">
    <template v-for="i in visible" :key="i.slot">
     <div v-if="i.empty" class="inventory-slot empty-slot"><small>{{i.slot_label}}</small><span>空</span><small>#{{i.slot}}</small></div>
     <button v-else type="button" class="inventory-slot" :class="{'slot-selected':selected?.slot===i.slot}" :aria-label="i.slot_label+'：'+i.name+'，数量'+number(i.quantity)" :aria-pressed="selected?.slot===i.slot" @click="select(i,$event)">
      <small>{{i.slot_label}}</small><GameImage :image="i.image" :label="i.name"/><b>{{i.name}}</b><small>×{{number(i.quantity)}}</small><span v-if="i.enhancement" class="slot-enhancement">+{{i.enhancement}}</span>
     </button>
    </template>
   </div><p v-if="!visible.length" class="empty">没有匹配的存档物品。</p>
   <div class="pagination"><button type="button" :disabled="page<=1" @click="page--">上一页槽位</button><span>{{page}} / {{pages}} · {{slots.length}} 槽</span><button type="button" :disabled="page>=pages" @click="page++">下一页槽位</button></div></div>
   <section v-if="selected" ref="detail" tabindex="-1" class="inventory-item-detail" role="region" aria-label="选中物品详情">
    <div class="section-title"><h3>{{selected.name}}</h3><button type="button" @click="close">收起详情</button></div>
    <GameImage :image="selected.image" :label="selected.name"/><p class="field-hint">{{selected.image?.note??'未安装图片包'}} · 物品 #{{selected.id}}</p>
    <dl class="character-facts"><div><dt>位置</dt><dd>{{selected.slot_label}} / #{{selected.slot}}</dd></div><div><dt>类型</dt><dd>{{selected.type_name}}</dd></div><div><dt>数量</dt><dd>{{number(selected.quantity)}}</dd></div><div><dt>等级</dt><dd>{{number(selected.level)}}</dd></div>
     <template v-if="selected.enhancement!==null&&selected.enhancement!==undefined"><div><dt>强化 / 锻造</dt><dd>+{{selected.enhancement}} / +{{selected.forge}}</dd></div><div><dt>耐久</dt><dd>{{selected.durability}}</dd></div><div><dt>增幅类型 / 数值</dt><dd>{{selected.amplify_type}} / {{selected.amplify_value}}</dd></div><div><dt>附魔 ID</dt><dd>{{selected.orb_id}}</dd></div><div><dt>封装原始标记</dt><dd>{{selected.sealed_raw}}</dd></div></template>
    </dl><p class="field-hint">数据库只读存档；不代表实时战斗属性、实际已开放格数或可发放状态。</p>
   </section>
  </div>
 </div>
</template>
