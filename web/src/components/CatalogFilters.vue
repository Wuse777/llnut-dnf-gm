<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import {useGmPreferences} from '../stores/gm/preferences'
const props=defineProps<{modelValue:Record<string,any>,facets?:any,pvf?:string,disabled?:boolean}>()
const emit=defineEmits<{'update:modelValue':[value:Record<string,any>],apply:[]}>()
const name=ref(''),warning=ref('')
const preferences=useGmPreferences('catalog-filter',()=>props.pvf)
const {items:saved,loading,saving,error:preferenceError,conflict}=preferences
const keys=['q','category','allowed_only','state','part','rarity','min_level','max_level','sort','job','weapon_type','set_id']
const legacy=ref<{id:string,name:string,filters:Record<string,any>}[]>([])
function clean(value:any,forServer=false){const result:Record<string,any>={};for(const key of keys){let v=value?.[key];if(v===''||v===undefined||v===null)continue;if(['rarity','min_level','max_level','set_id'].includes(key)){v=Number(v);if(!Number.isFinite(v))continue}if((typeof v==='string'&&v.length<=100)||(typeof v==='number'&&Number.isFinite(v))||typeof v==='boolean')result[key]=v}if(forServer){result.q??='';result.category??='';result.allowed_only??=false;result.sort??='id'}return result}
watch(()=>props.pvf,()=>{if(props.pvf)void preferences.load();try{const rows=JSON.parse(localStorage.getItem('dnfgm.catalog-filters.v1.'+(props.pvf||'unbound'))||'[]');legacy.value=Array.isArray(rows)?rows.filter(row=>typeof row?.name==='string'&&row.name.length<=40).slice(0,12):[]}catch{legacy.value=[]}},{immediate:true})
function update(k:string,v:any){emit('update:modelValue',{...props.modelValue,[k]:v})}
async function save(){const value=name.value.trim();if(!props.pvf||!value)return;warning.value='';if(await preferences.save(value,clean(props.modelValue,true))){name.value='';warning.value='筛选已保存，可在同一后台的其他浏览器使用。'}}
function apply(value:Record<string,any>){emit('update:modelValue',{q:'',category:'',allowed_only:false,part:'',rarity:'',min_level:'',max_level:'',sort:'id',job:'',weapon_type:'',set_id:'',...clean(value)});emit('apply')}
const existing=computed(()=>saved.value.some(row=>row.name===name.value.trim()))
</script>
<template>
 <details class="catalog-refine">
  <summary>组合筛选与常用条件 <small v-if="modelValue.part||modelValue.rarity!==''&&modelValue.rarity!=null||modelValue.min_level!==''&&modelValue.min_level!=null||modelValue.max_level!==''&&modelValue.max_level!=null">· 已设置</small></summary>
  <div class="refine-fields">
   <label>装备部位<select :value="modelValue.part||''" :disabled="disabled||!facets?.equipment_metadata" @change="update('part',($event.target as HTMLSelectElement).value)"><option value="">全部部位</option><option v-for="p in facets?.parts||[]" :key="p.code" :value="p.code">{{p.name}} · {{p.count}}</option></select></label>
   <label>适用职业<select :value="modelValue.job||''" :disabled="disabled||!facets?.extended_equipment_metadata" @change="update('job',($event.target as HTMLSelectElement).value)"><option value="">全部职业</option><option v-for="job in facets?.jobs||[]" :key="job.code" :value="job.code">{{job.name}} · {{job.count}}</option></select></label>
   <label>武器类型<select :value="modelValue.weapon_type||''" :disabled="disabled||!facets?.extended_equipment_metadata" @change="update('weapon_type',($event.target as HTMLSelectElement).value)"><option value="">全部武器</option><option v-for="weapon in facets?.weapon_types||[]" :key="weapon.code" :value="weapon.code">{{weapon.name}} · {{weapon.count}}</option></select></label>
   <label>所属套装<select :value="modelValue.set_id??''" :disabled="disabled||!facets?.extended_equipment_metadata" @change="update('set_id',($event.target as HTMLSelectElement).value)"><option value="">全部套装</option><option v-for="set in facets?.sets||[]" :key="set.id" :value="set.id">{{set.name}} · {{set.count}}</option></select></label>
   <label>PVF 品级<select :value="modelValue.rarity??''" :disabled="disabled||!facets?.equipment_metadata" @change="update('rarity',($event.target as HTMLSelectElement).value)"><option value="">全部品级</option><option v-for="r in facets?.rarities||[]" :key="r.value" :value="r.value">{{r.label}} · {{r.count}}</option></select></label>
   <label>最低等级<input :value="modelValue.min_level??''" aria-label="最低等级" type="number" min="0" max="1000" :disabled="disabled" @input="update('min_level',($event.target as HTMLInputElement).value)"></label>
   <label>最高等级<input :value="modelValue.max_level??''" aria-label="最高等级" type="number" min="0" max="1000" :disabled="disabled" @input="update('max_level',($event.target as HTMLInputElement).value)"></label>
   <label>排序<select :value="modelValue.sort||'id'" :disabled="disabled" @change="update('sort',($event.target as HTMLSelectElement).value)"><option value="id">编号顺序</option><option value="level_asc">等级从低到高</option><option value="level_desc">等级从高到低</option><option value="name">名称顺序</option></select></label>
  </div>
  <div class="button-row"><button type="button" class="primary" :disabled="disabled" @click="emit('apply')">应用组合筛选</button><button type="button" :disabled="disabled" @click="apply({...modelValue,part:'',rarity:'',min_level:'',max_level:'',sort:'id',job:'',weapon_type:'',set_id:''})">清除组合条件</button></div>
  <p v-if="facets&&!facets.equipment_metadata" class="field-hint">当前索引未提供装备元数据，部位与品级筛选暂不可用。</p>
  <div class="saved-filter-input"><label>保存当前筛选<input v-model="name" aria-label="常用筛选名称" maxlength="48" placeholder="例如：70级武器" :disabled="disabled||!pvf" @keydown.enter.prevent="save"></label><button type="button" :disabled="disabled||!pvf||!name.trim()||saving||conflict" @click="save">{{saving?'保存中…':existing?'更新同名筛选':'保存筛选'}}</button></div>
  <ul v-if="saved.length" class="saved-filters"><li v-for="row in saved" :key="row.name"><button type="button" :disabled="disabled" @click="apply(row.payload||{})">{{row.name}}</button><button type="button" class="ghost" :aria-label="'删除筛选 '+row.name" :disabled="disabled" @click="preferences.remove(row)">×</button></li></ul>
  <div class="button-row"><button type="button" :disabled="disabled||loading||saving||!pvf" @click="preferences.load">{{loading?'读取中…':'刷新方案'}}</button><span class="field-hint">筛选按 PVF 保存到后台；版本冲突时须刷新核对。</span></div><p v-if="preferenceError" role="alert" class="submit-error">{{preferenceError}}</p><details v-if="legacy.length"><summary>导入原浏览器筛选（{{legacy.length}} 项）</summary><button v-for="row in legacy" :key="row.id" type="button" :disabled="disabled" @click="apply(row.filters);name=row.name">{{row.name}}</button><p class="field-hint">应用后点击保存筛选，即可存入后台。</p></details><p class="field-hint">品级为 PVF 原始值，筛选和对比均不会发放物品。<span v-if="facets?.sets_truncated">套装较多，列表只展示当前索引的一部分。</span></p><p v-if="warning" role="status" class="field-hint">{{warning}}</p>
 </details>
</template>
<style scoped>
.catalog-refine{border:1px solid var(--line,#dedbd4);border-radius:12px;padding:12px;margin:12px 0}.catalog-refine summary{cursor:pointer;font-weight:600}.catalog-refine summary small{color:var(--muted,#777)}.refine-fields{display:grid;grid-template-columns:repeat(auto-fit,minmax(125px,1fr));gap:12px;margin:14px 0}.refine-fields label,.saved-filter-input label{display:grid;gap:6px;min-width:0}.saved-filter-input{display:flex;align-items:end;gap:8px;margin-top:16px;flex-wrap:wrap}.saved-filters{display:flex;gap:8px;flex-wrap:wrap;padding:0;list-style:none}.saved-filters li{display:flex;border:1px solid var(--line,#dedbd4);border-radius:8px;overflow:hidden}.saved-filters button{border:0;border-radius:0}input,select{max-width:100%;min-width:0}
</style>
