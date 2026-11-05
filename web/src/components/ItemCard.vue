<script setup lang="ts">
import {ref,watch} from 'vue'
import GameImage from './GameImage.vue'
import ItemFacts from './ItemFacts.vue'
import Modal from './Modal.vue'
const props=defineProps<{item:any,stored?:boolean}>()
const open=ref(false)
function inspect(event:Event){(event.currentTarget as HTMLElement).focus();open.value=true}
watch(()=>props.item,()=>{open.value=false})
const categories:Record<string,string>={equipment:'装备',material:'材料',consumable:'消耗品',special:'特殊物品'}
</script>
<template>
 <div class="shared-item-card">
  <GameImage :image="item.image" :label="item.name||'物品'"/>
  <div class="shared-item-copy"><button type="button" class="item-inspect" :aria-label="'查看物品详情 '+item.id+' '+(item.name||'物品')" @click="inspect"><b>{{item.name||'名称未收录'}}</b><span aria-hidden="true">↗</span></button><small>#{{item.id}} · {{item.type_name||categories[item.category]||'类型未收录'}} · {{item.level===null||item.level===undefined?'等级未知':'Lv. '+item.level}}</small><slot/></div>
 </div>
 <Teleport to="body"><Modal v-if="open" :title="'物品详情 · #'+item.id" drawer @close="open=false"><ItemFacts :item="item" :stored="stored"/><template #footer><span class="muted">仅查看，不执行游戏操作</span><button type="button" class="primary" @click="open=false">关闭物品详情</button></template></Modal></Teleport>
</template>
