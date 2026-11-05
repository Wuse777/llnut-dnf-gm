<script setup lang="ts">
import {computed} from 'vue'
import GameImage from './GameImage.vue'
const props=defineProps<{preview:any,currentItem?:any}>()
const sides=[{key:'before',title:'修改前'},{key:'after',title:'修改后'}] as const
const fields=[
 {key:'quantity',label:'存档数量'}, {key:'enhancement',label:'强化'},
 {key:'forge',label:'锻造'}, {key:'durability',label:'耐久'},
 {key:'amplify_type',label:'增幅类型代码'}, {key:'amplify_value',label:'增幅数值'},
 {key:'orb_id',label:'附魔'}, {key:'quality_raw',label:'品级原始值'},
]
const present=(v:unknown)=>v!==undefined&&v!==null
const number=(v:unknown)=>present(v)?typeof v==='number'?v.toLocaleString('zh-CN'):String(v):'未记录'
const value=(side:string)=>props.preview[side]??{}
const empty=(side:string)=>value(side).empty===true||value(side).id===0
const info=(side:string)=>props.preview[side+'_item_info']??(value(side).id===value('before').id?props.preview.item_info:undefined)??{}
const name=(side:string)=>empty(side)?'空槽位':info(side).name||(value(side).id===value('before').id?props.preview.item_name:undefined)||`未知物品 #${value(side).id??'—'}`
const image=(side:string)=>!empty(side)&&props.currentItem?.id===value(side).id?props.currentItem.image:null
const caption=(side:string)=>props.preview[side+'_enchantment']
const changed=(key:string)=>value('before')[key]!==value('after')[key]
const rows=computed(()=>fields.filter(f=>sides.some(s=>!empty(s.key)&&present(value(s.key)[f.key]))))
const count=computed(()=>rows.value.filter(f=>changed(f.key)).length)
const summary=computed(()=>empty('after')&&!empty('before')?'回收后该槽位为空；不影响其他槽位。':empty('before')&&!empty('after')?'将从指定快照恢复此槽位物品。':`本次有 ${count.value} 个展示字段发生变化；完整变更以操作清单为准。`)
</script>
<template>
 <section class="equipment-review" aria-label="装备修改前后对照">
  <div class="equipment-review-summary"><span class="review-mark" aria-hidden="true">⇄</span><p>{{summary}}</p></div>
  <div class="equipment-comparison">
   <section v-for="side in sides" :key="side.key" class="comparison-side" :class="{'comparison-after':side.key==='after','comparison-empty':empty(side.key)}" :aria-label="side.title">
    <div class="comparison-heading"><h4>{{side.title}}</h4><span v-if="side.key==='after'" class="comparison-tag">确认后写入</span><span v-else class="comparison-tag">存档快照</span></div>
    <div class="comparison-item"><GameImage v-if="!empty(side.key)" :image="image(side.key)" :label="name(side.key)"/><div><b>{{name(side.key)}}</b><p v-if="!empty(side.key)" class="field-hint">{{info(side.key).part_name||'部位未收录'}} · #{{value(side.key).id??'—'}}</p><p v-else class="field-hint">本槽位不含物品</p></div></div>
    <dl v-if="!empty(side.key)">
     <template v-for="field in rows" :key="field.key"><dt>{{field.label}}<span v-if="side.key==='after'&&changed(field.key)" class="changed-marker">已修改</span></dt><dd :class="{'changed':side.key==='after'&&changed(field.key)}">
      <template v-if="field.key==='orb_id'">{{caption(side.key)?.name||(value(side.key).orb_id?'#'+value(side.key).orb_id:present(value(side.key).orb_id)?'无附魔':'未记录')}}<small v-if="caption(side.key)?.id">#{{caption(side.key).id}}</small><small v-if="caption(side.key)?.summary">{{caption(side.key).summary}}</small></template>
      <template v-else>{{['enhancement','forge'].includes(field.key)&&present(value(side.key)[field.key])?'+':''}}{{number(value(side.key)[field.key])}}<small v-if="field.key==='durability'&&present(info(side.key).base_durability)">PVF基础值 {{number(info(side.key).base_durability)}}</small><small v-if="field.key==='amplify_type'">原始代码，未推断属性名称</small><small v-if="field.key==='quality_raw'">原始字段，不是品级百分比</small></template>
     </dd></template>
    </dl>
   </section>
  </div>
 </section>
</template>
<style scoped>
.equipment-review{margin:16px 0}.equipment-review-summary{display:flex;align-items:flex-start;gap:10px;padding:12px 14px;border:1px solid var(--border-color);border-radius:12px;background:var(--bg-secondary);font-size:12px;color:var(--text-secondary)}.equipment-review-summary p{margin:0;line-height:1.7}.review-mark{font-size:18px;line-height:1.2;color:var(--primary-color)}.equipment-comparison{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin-top:12px}.comparison-side{min-width:0;padding:16px;border:1px solid var(--border-color);border-radius:14px;background:var(--bg-secondary)}.comparison-after{border-color:color-mix(in srgb,var(--primary-color) 40%,var(--border-color));background:linear-gradient(145deg,color-mix(in srgb,var(--primary-color) 5%,var(--bg-secondary)),var(--bg-secondary))}.comparison-heading{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:14px}.comparison-heading h4{margin:0;font-size:13px;color:var(--text-secondary)}.comparison-tag{font-size:10px;color:var(--text-secondary);border:1px solid var(--border-color);border-radius:20px;padding:3px 7px}.comparison-item{display:flex;gap:12px;align-items:center;min-width:0;min-height:48px}.comparison-item>div{min-width:0}.comparison-item b{display:block;overflow-wrap:anywhere;line-height:1.6;font-size:14px}.comparison-item p{margin:4px 0 0}.equipment-comparison dl{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:12px 8px;margin:16px 0 0;padding-top:14px;border-top:1px solid var(--border-color);font-size:12px}.equipment-comparison dt{color:var(--text-secondary);overflow-wrap:anywhere}.equipment-comparison dd{margin:0;text-align:right;overflow-wrap:anywhere;font-variant-numeric:tabular-nums}.equipment-comparison dd small{display:block;color:var(--text-secondary);margin-top:4px;font-size:10px;line-height:1.6}.changed-marker{display:inline-block;margin-left:5px;font-size:9px;color:var(--primary-color)}.equipment-comparison .changed{color:var(--primary-color);font-weight:600}.comparison-empty{border-style:dashed}@media(max-width:600px){.equipment-comparison{grid-template-columns:1fr}.comparison-side{padding:14px}}
</style>
