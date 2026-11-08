<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import GameImage from './GameImage.vue'
import type {AssetImage} from './GameImage.vue'
const props=defineProps<{slots:any[],selectedSlot?:number,jobPreview?:AssetImage|null,outfitPreview?:AssetImage|null}>()
const emit=defineEmits<{select:[item:any,event:Event]}>()
const showPose=ref(true),outfitFailed=ref(false),jobFailed=ref(false)
const validImage=(image:AssetImage|null|undefined,kind:string)=>image?.state==='ready'&&image.source_kind===kind&&/^\/dnf-gm\/api\/v1\/assets\/[a-f0-9]{64}\/[a-f0-9]{64}\.png$/.test(image.url??'')
const savedOutfit=computed(()=>!outfitFailed.value&&props.outfitPreview?.pose==='waiting_first_frame'&&validImage(props.outfitPreview,'saved_avatar_outfit'))
const currentPreview=computed(()=>savedOutfit.value?props.outfitPreview:!jobFailed.value&&validImage(props.jobPreview,'client_default_pose')?props.jobPreview:null)
const poseSource=computed(()=>currentPreview.value?.url??null)
const poseLabel=computed(()=>savedOutfit.value?'服装存档首帧':'基础职业默认站姿')
watch(()=>[props.outfitPreview?.url,props.jobPreview?.url],()=>{outfitFailed.value=false;jobFailed.value=false;showPose.value=true})
const poseAvailable=computed(()=>!!poseSource.value)
function failPose(){if(savedOutfit.value)outfitFailed.value=true;else jobFailed.value=true}
// The ordering matches this adapter's EQUIP_SLOTS, not PVF item categories.
const positions:Record<number,{column:number|string,row:number}>={3:{column:1,row:1},2:{column:1,row:2},6:{column:1,row:3},4:{column:1,row:4},5:{column:1,row:5},7:{column:5,row:1},8:{column:5,row:2},9:{column:5,row:3},10:{column:5,row:4},11:{column:5,row:5},0:{column:'1 / 3',row:6},1:{column:'4 / 6',row:6}}
const known=computed(()=>props.slots.filter(i=>Number.isInteger(i.slot)&&Object.hasOwn(positions,i.slot)))
const extra=computed(()=>props.slots.filter(i=>!Number.isInteger(i.slot)||!Object.hasOwn(positions,i.slot)))
const position=(slot:number)=>({gridColumn:positions[slot].column,gridRow:positions[slot].row})
function number(v:unknown){return v===null||v===undefined?'未知':Number(v).toLocaleString('zh-CN')}
</script>
<template>
 <div class="equipment-body-view">
  <div v-if="poseAvailable" class="equipment-pose-switch" role="group" aria-label="装备图中心展示"><button type="button" :aria-pressed="showPose" @click="showPose=true">{{poseLabel}}</button><button type="button" :aria-pressed="!showPose" @click="showPose=false">槽位示意</button></div>
  <div class="equipment-body-board" role="group" aria-label="角色穿戴存档槽位">
   <div class="equipment-outline"><template v-if="showPose&&poseAvailable"><img class="equipment-default-pose" :src="poseSource!" :alt="poseLabel" loading="lazy" decoding="async" @error="failPose"><span>{{poseLabel}}</span><small v-if="savedOutfit">服装存档 · 非实时外观<br>不含武器、染色或变身效果</small><small v-else>客户端首帧 · 非当前装备外观<br>不代表转职或觉醒形态</small></template><template v-else><svg aria-hidden="true" viewBox="0 0 120 240" fill="none"><circle cx="60" cy="29" r="19"/><path d="M36 61C46 54 74 54 84 61L103 122L88 128L75 91L79 145L88 221H69L60 161L51 221H32L41 145L45 91L32 128L17 122Z"/><path class="outline-detail" d="M43 142H77M60 65V143M41 92H79"/></svg><span>穿戴存档</span><small>槽位示意 · 非角色实际外观</small></template></div>
   <template v-for="i in known" :key="i.slot">
    <div v-if="i.empty" class="inventory-slot equipment-body-slot empty-slot" :style="position(i.slot)"><small>{{i.slot_label}}</small><span class="equipment-empty-mark" aria-hidden="true">＋</span><span>空</span></div>
    <button v-else type="button" class="inventory-slot equipment-body-slot" :style="position(i.slot)" :class="{'slot-selected':selectedSlot===i.slot}" :aria-pressed="selectedSlot===i.slot" :aria-label="i.slot_label+'：'+i.name+'，数量'+number(i.quantity)" @click="emit('select',i,$event)"><small>{{i.slot_label}}</small><GameImage :image="i.image" :label="i.name" :rarity-name="i.rarity_name" :rarity="i.rarity"/><b>{{i.name}}</b><span v-if="i.enhancement" class="equipment-plus">+{{i.enhancement}}</span></button>
   </template>
  </div>
  <p class="equipment-layout-caption">按存档槽位展示装备；点击查看详情。物品槽位不含时装与宠物；中心预览类型与适用范围单独标注。</p>
  <p v-if="showPose&&poseAvailable&&currentPreview?.note" class="equipment-layout-caption">{{currentPreview.note}}</p>
  <p v-if="!savedOutfit&&outfitPreview?.note" class="equipment-layout-caption">服装预览：{{outfitPreview.note}}</p>
  <section v-if="extra.length" class="equipment-extra-slots" aria-label="其他存档槽位"><h3>其他存档槽位</h3><div class="inventory-slot-grid"><template v-for="i in extra" :key="i.slot"><div v-if="i.empty" class="inventory-slot empty-slot"><small>{{i.slot_label}}</small><span>空</span><small>#{{i.slot}}</small></div><button v-else type="button" class="inventory-slot" :aria-label="i.slot_label+'：'+i.name" :aria-pressed="selectedSlot===i.slot" @click="emit('select',i,$event)"><small>{{i.slot_label}} · #{{i.slot}}</small><GameImage :image="i.image" :label="i.name" :rarity-name="i.rarity_name" :rarity="i.rarity"/><b>{{i.name}}</b></button></template></div></section>
 </div>
</template>
<style scoped>
.equipment-body-view{min-width:0}.equipment-body-board{display:grid;grid-template-columns:minmax(76px,1fr) minmax(36px,.6fr) minmax(28px,.6fr) minmax(36px,.6fr) minmax(76px,1fr);grid-template-rows:repeat(5,minmax(96px,auto)) minmax(96px,auto);gap:8px;max-width:580px;margin-inline:auto;padding:16px;border:1px solid var(--border-color);border-radius:14px;background:radial-gradient(ellipse at 50% 42%,var(--bg-tertiary),var(--bg-primary) 65%)}
.equipment-pose-switch{display:flex;justify-content:center;gap:6px;flex-wrap:wrap;margin:0 0 12px}.equipment-pose-switch button{font-size:11px;padding:7px 10px}.equipment-pose-switch button[aria-pressed=true]{color:var(--primary-color);border-color:var(--primary-color);background:var(--bg-secondary)}.equipment-default-pose{object-fit:contain;image-rendering:pixelated;max-width:100%;width:auto;max-height:220px;height:auto}
.equipment-body-slot{min-height:96px;padding:7px 5px;gap:4px;box-shadow:0 2px 6px #00000004}.equipment-body-slot small{font-size:10px;color:var(--text-secondary)}.equipment-body-slot b{max-width:100%;font-size:10px;line-height:1.3;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.equipment-body-slot:focus-visible{outline:2px solid var(--primary-color);outline-offset:2px}.equipment-body-slot .game-image{margin:0}.equipment-body-slot.empty-slot{border-style:dashed;background:var(--bg-primary)}.equipment-empty-mark{font-size:22px;font-weight:300;opacity:.35;line-height:1.5}.equipment-plus{position:absolute;top:23px;right:3px;font-size:10px;padding:1px 4px;background:var(--bg-primary);border:1px solid var(--border-color);border-radius:4px;font-variant-numeric:tabular-nums}
.equipment-outline{grid-column:2/5;grid-row:1/6;display:flex;flex-direction:column;justify-content:center;align-items:center;gap:10px;padding:10px;min-width:0;text-align:center;color:var(--text-tertiary)}.equipment-outline svg{width:100%;max-width:150px;stroke:var(--border-hover);stroke-width:1.2;fill:var(--bg-secondary)}.equipment-outline .outline-detail{stroke:var(--border-color);stroke-dasharray:3 3;fill:none}.equipment-outline>span{font-size:13px;color:var(--text-secondary)}.equipment-outline>small{font-size:10px;line-height:1.7}.equipment-layout-caption{max-width:580px;margin:10px auto 0;font-size:11px;color:var(--text-secondary);line-height:1.7}.equipment-extra-slots{margin-top:16px}.equipment-extra-slots h3{font-size:12px;color:var(--text-secondary)}
@media(max-width:680px){.equipment-body-board{padding:10px;gap:6px;grid-template-columns:minmax(69px,1fr) minmax(25px,.6fr) minmax(20px,.6fr) minmax(25px,.6fr) minmax(69px,1fr);grid-template-rows:repeat(6,minmax(88px,auto))}.equipment-body-slot{min-height:88px}.equipment-outline{padding:5px}.equipment-outline>span{font-size:12px}.equipment-outline>small{font-size:9px}.equipment-body-slot .game-image{width:36px;height:36px;flex-basis:36px}.equipment-body-slot b{-webkit-line-clamp:1}}
</style>
