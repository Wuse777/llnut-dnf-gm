<script setup lang="ts">
import {computed} from 'vue'
import GameImage from './GameImage.vue'
const props=defineProps<{items:any[]}>()
const emit=defineEmits<{remove:[id:number],clear:[]}>()
const attributes=computed<[string,string][]>(()=>Array.from(new Map<string,string>(props.items.flatMap(i=>(i.base_attributes||[]).map((a:any)=>[a.tag,a.label] as [string,string]))).entries()))
function values(item:any,tag:string){return item.base_attributes?.find((a:any)=>a.tag===tag)?.values?.join(' / ')??'未收录'}
</script>
<template>
 <section v-if="items.length" class="item-compare" aria-label="装备对比">
  <div class="section-title"><h3>物品对比 · {{items.length}} / 4</h3><button type="button" @click="emit('clear')">清空对比</button></div>
  <p class="field-hint">同一 PVF 下的顶层定义原值，已排除显式成对段；不解释条件、附魔、角色加成、随机品级或强化，也未换算单位。</p>
  <div class="compare-scroll" tabindex="0" aria-label="物品对比表，可横向滚动"><table><thead><tr><th scope="col">对比项目</th><th v-for="i in items" :key="i.id" scope="col"><GameImage :image="i.image" :label="i.name" :rarity="i.rarity" :rarity-name="i.rarity_name"/><b>{{i.name}}</b><small>#{{i.id}}</small><button type="button" :aria-label="'移出对比 '+i.id" @click="emit('remove',i.id)">移出</button></th></tr></thead><tbody>
   <tr><th scope="row">部位</th><td v-for="i in items" :key="i.id">{{i.part_name||'未收录'}}</td></tr><tr><th scope="row">等级</th><td v-for="i in items" :key="i.id">{{i.level??'未收录'}}</td></tr><tr><th scope="row">PVF 品级</th><td v-for="i in items" :key="i.id">{{i.rarity_name??i.rarity??'未收录'}}</td></tr><tr><th scope="row">基础耐久</th><td v-for="i in items" :key="i.id">{{i.durability??'未收录'}}</td></tr>
   <tr v-for="[tag,label] in attributes" :key="tag"><th scope="row">{{label}}</th><td v-for="i in items" :key="i.id">{{values(i,tag)}}</td></tr>
  </tbody></table></div>
 </section>
</template>
<style scoped>
.item-compare{margin:16px 0;padding:16px;border:1px solid var(--line,#dedbd4);border-radius:12px;background:var(--panel,#faf9f6)}.compare-scroll{overflow-x:auto;overscroll-behavior-x:contain}.compare-scroll table{width:100%;min-width:380px}.compare-scroll th,.compare-scroll td{padding:10px;min-width:100px;vertical-align:top}.compare-scroll thead th:not(:first-child){min-width:155px}.compare-scroll th>b,.compare-scroll th>small{display:block;margin:6px 0}.compare-scroll tbody th{font-weight:500;color:var(--muted,#777)}
</style>
