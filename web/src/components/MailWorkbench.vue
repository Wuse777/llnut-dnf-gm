<script setup lang="ts">
import {ref,nextTick} from 'vue'
const props=defineProps<{modelValue:'items'|'draft',count:number,quantity:number,gold:number,hasCurrencies:boolean,busy:boolean}>()
const emit=defineEmits<{'update:modelValue':[value:'items'|'draft']}>()
const root=ref<HTMLElement|null>(null)
async function select(value:'items'|'draft'){
 if(props.busy)return
 emit('update:modelValue',value)
 await nextTick()
 root.value?.scrollIntoView?.({block:'start',behavior:'instant'})
 root.value?.querySelector<HTMLElement>('.mail-pane-buttons button[aria-pressed=true]')?.focus({preventScroll:true})
}
</script>
<template>
 <div ref="root" class="mail-workbench-frame" :data-pane="modelValue">
  <nav class="mail-pane-nav" aria-label="邮件工作区切换">
   <div class="mail-pane-buttons"><button :disabled="busy" :aria-pressed="modelValue==='items'" aria-controls="mail-pane-items" @click="select('items')">选择物品</button><button :disabled="busy" :aria-pressed="modelValue==='draft'" aria-controls="mail-pane-draft" @click="select('draft')">奖励与预览 <span class="count-badge">{{count}}</span></button></div>
   <small role="status" aria-live="polite">{{quantity.toLocaleString('zh-CN')}} 件 · {{gold.toLocaleString('zh-CN')}} 金币<template v-if="hasCurrencies"> · 含账号货币</template></small>
  </nav>
  <div class="mail-workbench">
   <div id="mail-pane-items" class="mail-pane mail-pane-items"><slot name="items"/></div>
   <div id="mail-pane-draft" class="mail-pane mail-pane-draft"><slot name="draft" :select="select"/></div>
  </div>
 </div>
</template>
<style scoped>
.mail-workbench-frame{min-width:0;scroll-margin-top:16px}.mail-pane{min-width:0}.mail-pane-draft{align-self:stretch}.mail-pane-nav{display:none}.mail-pane>.panel{margin:0}
@media(max-width:1150px){
 .mail-workbench-frame{scroll-margin-top:12px}.mail-pane-nav{position:sticky;top:8px;z-index:30;display:grid;gap:5px;padding:8px;margin-bottom:12px;border:1px solid var(--border-color);border-radius:12px;background:var(--bg-primary);box-shadow:0 4px 16px #0000000a}.mail-pane-buttons{display:flex;gap:6px}.mail-pane-buttons>button{flex:1;min-width:0;padding:9px 8px}.mail-pane-buttons>button[aria-pressed=true]{background:var(--primary-color);border-color:var(--primary-color);color:var(--primary-contrast)}.mail-pane-nav>small{color:var(--text-secondary);text-align:center;overflow-wrap:anywhere}.mail-workbench{display:block}.mail-workbench-frame[data-pane=draft] .mail-pane-items,.mail-workbench-frame[data-pane=items] .mail-pane-draft{display:none}.mail-pane-draft{scroll-margin-top:100px}
}
</style>
