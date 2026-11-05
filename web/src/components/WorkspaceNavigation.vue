<script setup lang="ts">
import {computed,ref,watch} from 'vue'
const props=defineProps<{tabs:string[][],icons:Record<string,string>,current:string,collapsed:boolean,busy:boolean,mailCount:number}>()
const emit=defineEmits<{choose:[id:string]}>()
const query=ref('')
watch(()=>props.collapsed,value=>{if(value)query.value=''})
const sections=[
 {title:'工作台',ids:['overview','accounts','online','support']},
 {title:'奖励与运营',ids:['mail','mail-center','gifts','reward-jobs','schedules','native-controls']},
 {title:'道具与记录',ids:['catalog','unlock-center','economy','audit']},
 {title:'系统管理',ids:['operations-dashboard','capabilities','maintenance','compatibility']},
]
const groups=computed(()=>{
 const needle=query.value.trim().toLocaleLowerCase()
 const matches=(tab:string[])=>!needle||tab.some(v=>v.toLocaleLowerCase().includes(needle))
 const known=new Set(sections.flatMap(s=>s.ids))
 return [...sections.map(s=>({title:s.title,items:s.ids.map(id=>props.tabs.find(t=>t[0]===id)).filter((t):t is string[]=>!!t&&matches(t))})),
  {title:'其他功能',items:props.tabs.filter(t=>!known.has(t[0])&&matches(t))}].filter(g=>g.items.length)
})
</script>
<template>
 <nav class="workspace-nav" aria-label="功能导航">
  <div class="nav-search"><label><span class="sr-only">搜索功能</span><input v-model="query" type="search" placeholder="搜索功能…" :disabled="busy" @keydown.esc.stop="query=''" /></label><button v-if="query" class="ghost" aria-label="清空功能搜索" @click="query=''">×</button></div>
  <section v-for="group in groups" :key="group.title" class="nav-section" :aria-label="group.title">
   <small class="nav-label">{{group.title}}</small>
   <button v-for="[id,name] in group.items" :key="id" :class="{active:current===id}" :aria-current="current===id?'page':undefined" :title="collapsed?name:undefined" :disabled="busy" @click="emit('choose',id)">
    <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path :d="icons[id]"/></svg><span class="nav-text">{{name}}</span><small v-if="id==='mail'&&mailCount" class="count-badge">{{mailCount}}</small>
   </button>
  </section>
  <div v-if="!groups.length" class="nav-no-results" role="status">没有匹配的功能<button class="ghost" @click="query=''">显示全部功能</button></div>
 </nav>
</template>
<style scoped>
.workspace-nav{min-height:0;flex:1;overflow-y:auto;scrollbar-width:thin;padding-bottom:8px;display:block}.nav-section{display:grid;gap:3px;margin-top:15px}.nav-section:first-of-type{margin-top:10px}.nav-label{padding:0 12px 4px;font-size:10px;letter-spacing:.09em;color:var(--text-tertiary)}.nav-section>button{width:100%;justify-content:flex-start}.nav-search{position:relative;margin:0 3px}.nav-search input{padding:9px 30px 9px 11px;font-size:12px;background:var(--bg-secondary)}.nav-search>button{position:absolute;right:3px;top:3px;padding:3px 7px;min-height:28px;font-size:18px}.nav-no-results{padding:20px 6px;color:var(--text-secondary);font-size:12px;text-align:center}.nav-no-results button{margin-top:12px;width:100%}.sr-only{position:absolute;width:1px;height:1px;padding:0;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap}
@media(min-width:769px){:global(.is-collapsed) .nav-search,:global(.is-collapsed) .nav-label{display:none}:global(.is-collapsed) .nav-section{margin-top:8px;padding-top:8px;border-top:1px solid var(--border-color)}:global(.is-collapsed) .nav-section:first-of-type{border:0;padding-top:0;margin-top:0}:global(.is-collapsed) .nav-section>button{padding-inline:8px;justify-content:center}}
</style>
