<script setup lang="ts">
import {computed,ref,watch} from 'vue'
const props=defineProps<{modelValue:Record<string,any>,facets?:any,pvf?:string,disabled?:boolean}>()
const emit=defineEmits<{'update:modelValue':[value:Record<string,any>],apply:[]}>()
const name=ref(''),saved=ref<{id:string,name:string,filters:Record<string,any>}[]>([]),warning=ref('')
const key=computed(()=>'dnfgm.catalog-filters.v1.'+(props.pvf||'unbound'))
const keys=['q','category','allowed_only','state','part','rarity','min_level','max_level','sort']
function clean(value:any){const result:Record<string,any>={};for(const k of keys){const v=value?.[k];if((typeof v==='string'&&v.length<=100)||(typeof v==='number'&&Number.isFinite(v))||typeof v==='boolean')result[k]=v}return result}
watch(key,()=>{try{const rows=JSON.parse(localStorage.getItem(key.value)||'[]');saved.value=Array.isArray(rows)?rows.filter(r=>typeof r?.id==='string'&&typeof r?.name==='string'&&r.name.length<=40).slice(0,12).map(r=>({...r,filters:clean(r.filters)})):[]}catch{saved.value=[];warning.value='浏览器保存的筛选无法读取，可以重新保存。'}},{immediate:true})
function update(k:string,v:any){emit('update:modelValue',{...props.modelValue,[k]:v})}
function persist(){try{localStorage.setItem(key.value,JSON.stringify(saved.value));warning.value=''}catch{warning.value='浏览器无法保存筛选，当前查询仍可使用。'}}
function save(){if(!props.pvf||!name.value.trim())return;if(saved.value.length>=12){warning.value='最多保存12组筛选，请先删除不再使用的筛选。';return}saved.value.push({id:crypto.randomUUID(),name:name.value.trim(),filters:clean(props.modelValue)});name.value='';persist()}
function apply(value:Record<string,any>){emit('update:modelValue',clean(value));emit('apply')}
</script>
<template>
 <details class="catalog-refine">
  <summary>组合筛选与常用条件 <small v-if="modelValue.part||modelValue.rarity!==''&&modelValue.rarity!=null||modelValue.min_level!==''&&modelValue.min_level!=null||modelValue.max_level!==''&&modelValue.max_level!=null">· 已设置</small></summary>
  <div class="refine-fields">
   <label>装备部位<select :value="modelValue.part||''" :disabled="disabled||!facets?.equipment_metadata" @change="update('part',($event.target as HTMLSelectElement).value)"><option value="">全部部位</option><option v-for="p in facets?.parts||[]" :key="p.code" :value="p.code">{{p.name}} · {{p.count}}</option></select></label>
   <label>PVF 品级<select :value="modelValue.rarity??''" :disabled="disabled||!facets?.equipment_metadata" @change="update('rarity',($event.target as HTMLSelectElement).value)"><option value="">全部品级</option><option v-for="r in facets?.rarities||[]" :key="r.value" :value="r.value">{{r.label}} · {{r.count}}</option></select></label>
   <label>最低等级<input :value="modelValue.min_level??''" aria-label="最低等级" type="number" min="0" max="1000" :disabled="disabled" @input="update('min_level',($event.target as HTMLInputElement).value)"></label>
   <label>最高等级<input :value="modelValue.max_level??''" aria-label="最高等级" type="number" min="0" max="1000" :disabled="disabled" @input="update('max_level',($event.target as HTMLInputElement).value)"></label>
   <label>排序<select :value="modelValue.sort||'id'" :disabled="disabled" @change="update('sort',($event.target as HTMLSelectElement).value)"><option value="id">编号顺序</option><option value="level_asc">等级从低到高</option><option value="level_desc">等级从高到低</option><option value="name">名称顺序</option></select></label>
  </div>
  <div class="button-row"><button type="button" class="primary" :disabled="disabled" @click="emit('apply')">应用组合筛选</button><button type="button" :disabled="disabled" @click="apply({...modelValue,part:'',rarity:'',min_level:'',max_level:'',sort:'id'})">清除组合条件</button></div>
  <p v-if="facets&&!facets.equipment_metadata" class="field-hint">当前索引未提供装备元数据，部位与品级筛选暂不可用。</p>
  <div class="saved-filter-input"><label>保存当前筛选<input v-model="name" aria-label="常用筛选名称" maxlength="40" placeholder="例如：70级武器" :disabled="disabled||!pvf" @keydown.enter.prevent="save"></label><button type="button" :disabled="disabled||!pvf||!name.trim()" @click="save">保存筛选</button></div>
  <ul v-if="saved.length" class="saved-filters"><li v-for="row in saved" :key="row.id"><button type="button" :disabled="disabled" @click="apply(row.filters)">{{row.name}}</button><button type="button" class="ghost" :aria-label="'删除筛选 '+row.name" :disabled="disabled" @click="saved=saved.filter(r=>r.id!==row.id);persist()">×</button></li></ul>
  <p class="field-hint">常用条件仅保存在此浏览器，按 PVF 版本区分。品级显示来源原始值；筛选和对比均不会发放物品。</p><p v-if="warning" role="status" class="field-hint">{{warning}}</p>
 </details>
</template>
<style scoped>
.catalog-refine{border:1px solid var(--line,#dedbd4);border-radius:12px;padding:12px;margin:12px 0}.catalog-refine summary{cursor:pointer;font-weight:600}.catalog-refine summary small{color:var(--muted,#777)}.refine-fields{display:grid;grid-template-columns:repeat(auto-fit,minmax(125px,1fr));gap:12px;margin:14px 0}.refine-fields label,.saved-filter-input label{display:grid;gap:6px;min-width:0}.saved-filter-input{display:flex;align-items:end;gap:8px;margin-top:16px;flex-wrap:wrap}.saved-filters{display:flex;gap:8px;flex-wrap:wrap;padding:0;list-style:none}.saved-filters li{display:flex;border:1px solid var(--line,#dedbd4);border-radius:8px;overflow:hidden}.saved-filters button{border:0;border-radius:0}input,select{max-width:100%;min-width:0}
</style>
