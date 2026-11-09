<script setup lang="ts">
import {computed,ref,watch,useId} from 'vue'
import GameImage from './GameImage.vue'
import ItemFacts from './ItemFacts.vue'
import Modal from './Modal.vue'
import ItemQuickFacts from './ItemQuickFacts.vue'
const props=defineProps<{item:any,stored?:boolean,compact?:boolean}>()
const open=ref(false)
const tooltipId=useId()
const quality=computed(()=>({普通:'normal',高级:'advanced',稀有:'rare',神器:'unique',史诗:'epic',勇者:'chronicle',传说:'legendary'} as Record<string,string>)[props.item.rarity_name]||'unknown')
function inspect(event:Event){(event.currentTarget as HTMLElement).focus();open.value=true}
watch(()=>props.item,()=>{open.value=false})
const categories:Record<string,string>={equipment:'装备',material:'材料',consumable:'消耗品',special:'特殊物品'}
</script>
<template>
 <div class="shared-item-card" :class="[{'shared-item-card--compact':compact},'item-rarity-'+quality]">
  <GameImage :image="item.image" :label="item.name||'物品'" :rarity-name="item.rarity_name" :rarity="item.rarity"/>
  <div class="shared-item-copy"><button type="button" class="item-inspect" :aria-describedby="tooltipId" :aria-label="'查看物品详情 '+item.id+' '+(item.name||'物品')" @click="inspect"><b>{{item.name||'名称未收录'}}</b><span aria-hidden="true">↗</span></button><small>#{{item.id}} · {{item.type_name||categories[item.category]||'类型未收录'}} · {{item.level===null||item.level===undefined?'等级未知':'Lv. '+item.level}}<template v-if="compact&&item.rarity_name"> · {{item.rarity_name}}</template></small><slot/></div>
  <div :id="tooltipId" role="tooltip" class="item-hover-facts"><ItemQuickFacts :item="item" :stored="stored"/></div>
 </div>
 <Teleport to="body"><Modal v-if="open" :title="'物品详情 · #'+item.id" drawer @close="open=false"><ItemFacts :item="item" :stored="stored"/><template #footer><span class="muted">仅查看，不执行游戏操作</span><button type="button" class="primary" @click="open=false">关闭物品详情</button></template></Modal></Teleport>
</template>
<style scoped>
.shared-item-card{position:relative;min-width:0}.item-inspect b{color:var(--item-rarity-color,var(--text-primary))}.item-rarity-advanced{--item-rarity-color:#4779ad}.item-rarity-rare{--item-rarity-color:#8661ad}.item-rarity-unique{--item-rarity-color:#ac5279}.item-rarity-epic{--item-rarity-color:#927128}.item-rarity-chronicle{--item-rarity-color:#896e46}.item-rarity-legendary{--item-rarity-color:#a36c36}.item-hover-facts{display:none;position:absolute;left:44px;top:calc(100% + 6px);z-index:90;pointer-events:none}.shared-item-card--compact{display:flex;align-items:center;gap:10px}.shared-item-card--compact .shared-item-copy{display:grid;gap:1px;min-width:0}.shared-item-card--compact .item-inspect{padding:0;min-height:0;font-size:13px;line-height:19px;overflow:hidden;max-width:100%;border:0;justify-content:flex-start}.shared-item-card--compact .item-inspect b{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.shared-item-card--compact .item-inspect>span{display:none}.shared-item-card--compact .shared-item-copy>small{font-size:10px;line-height:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--text-secondary)}.shared-item-card--compact :deep(.game-image){width:36px;height:36px;min-width:36px;flex:none;border-radius:5px}
@media(hover:hover) and (min-width:769px){.shared-item-card:has(.item-inspect:hover) .item-hover-facts,.shared-item-card:has(.item-inspect:focus-visible) .item-hover-facts{display:block}}
:global(html.dark) .item-rarity-advanced{--item-rarity-color:#91b8e7}:global(html.dark) .item-rarity-rare{--item-rarity-color:#bd9ae6}:global(html.dark) .item-rarity-unique{--item-rarity-color:#e59ab8}:global(html.dark) .item-rarity-epic{--item-rarity-color:#ead083}:global(html.dark) .item-rarity-chronicle{--item-rarity-color:#d0b28c}:global(html.dark) .item-rarity-legendary{--item-rarity-color:#e8aa78}
</style>
