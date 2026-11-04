<script setup lang="ts">
import GameImage from './GameImage.vue'
defineProps<{request:any}>()
const labels:Record<string,string>={matched:'已关联存档物品',ambiguous:'多处关联，不能确定唯一物品',partial:'容器存档不完整',unmapped:'未在已读取容器中关联'}
</script>
<template><div class="unlock-item"><template v-if="request.item"><GameImage :image="request.item.image" :label="request.item.name"/><b>{{request.item.name}}</b><small class="cell-note">物品 #{{request.item.id}} · {{request.item.container_name}} / {{request.item.slot_label}} #{{request.item.slot}}</small><small v-if="request.item.enhancement!==null" class="cell-note">强化 +{{request.item.enhancement}} · 锻造 +{{request.item.forge}}</small></template><span v-else>锁定记录 #{{request.lock_key}}</span><small class="cell-note">{{labels[request.mapping_state]||'物品关联信息尚不可用'}}</small><details v-if="request.candidates?.length"><summary>{{request.candidates.length}} 个候选位置</summary><ul><li v-for="i in request.candidates" :key="i.container+':'+i.slot">{{i.name}} #{{i.id}} · {{i.container_name}} / {{i.slot_label}}</li></ul></details></div></template>
