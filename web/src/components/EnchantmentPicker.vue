<script setup lang="ts">
import {computed,onBeforeUnmount,ref} from 'vue'
import {api,uncertainMessage} from '../api'
import GameImage from './GameImage.vue'
const props=defineProps<{modelValue:string,current?:any,disabled?:boolean}>()
const emit=defineEmits(['update:modelValue','error'])
const q=ref(''),page=ref(1),more=ref(false),rows=ref<any[]>([]),busy=ref(false),error=ref(''),loaded=ref(false),state=ref(''),metadata=ref('')
const picked=ref<any>(null)
const selected=computed(()=>[picked.value,props.current].find(x=>x&&String(x.id)===props.modelValue.trim()))
let alive=true
onBeforeUnmount(()=>{alive=false})
async function search(next=1){
 if(busy.value||props.disabled)return;busy.value=true;error.value=''
 try{const result=await api('/catalog/enchantments?'+new URLSearchParams({q:q.value.trim(),page:String(next)}));if(!alive)return;rows.value=result.items;page.value=result.page;more.value=result.has_more;state.value=result.state;metadata.value=result.metadata_state;loaded.value=true}
 catch(e){if(alive){error.value=uncertainMessage(e);emit('error',e)}}finally{if(alive)busy.value=false}
}
function choose(row:any){if(props.disabled||state.value!=='ok')return;picked.value=row;emit('update:modelValue',String(row.id))}
</script>
<template>
 <section class="enchantment-picker" aria-label="附魔选择">
  <div class="section-title"><h4>附魔</h4><button type="button" :disabled="disabled" @click="emit('update:modelValue','0')">清除附魔</button></div>
  <p class="enchantment-selection"><b>{{modelValue.trim()==='0'?'无附魔':selected?.name||'手动编号 · 待预览校验'}}</b><span v-if="modelValue.trim()!=='0'"> #{{modelValue}}</span><small v-if="selected?.summary">{{selected.summary}}</small></p>
  <details><summary>按名称、编号或效果查找附魔</summary>
   <div class="enchantment-search"><label>附魔名称、编号或效果<input v-model="q" aria-label="附魔搜索条件" maxlength="80" :disabled="disabled||busy" placeholder="例如：烈焰彼诺修、火属性、3604" @keydown.enter.prevent="search(1)"></label><button type="button" :disabled="disabled||busy" @click="search(1)">{{busy?'查询中…':'查询附魔'}}</button></div>
   <p v-if="error" class="field-error" role="alert">{{error}}</p>
   <p v-if="loaded&&metadata!=='ok'" class="notice">尚未安装附魔定义索引；仍可填写编号并生成预览。</p>
   <p v-else-if="loaded&&state!=='ok'" class="notice">PVF版本不匹配，结果仅供查询，当前不能选择。</p>
   <p v-if="loaded&&metadata==='ok'&&!rows.length" class="empty">未找到明确含附魔定义的物品。名称含“宝珠”不一定是附魔。</p>
   <div v-if="rows.length" class="enchantment-results"><article v-for="row in rows" :key="row.id" :class="{'is-selected':String(row.id)===modelValue.trim()}"><GameImage :image="row.image" :label="row.name"/><div><b>{{row.name}}</b><small>#{{row.id}} · {{row.target_names.length?row.target_names.join('、'):'未标注适用部位'}}</small><p>{{row.summary}}</p></div><button type="button" :aria-label="'选择附魔 '+row.id+' '+row.name" :disabled="disabled||state!=='ok'" @click="choose(row)">{{String(row.id)===modelValue.trim()?'已选择':'选择'}}</button></article></div>
   <div v-if="loaded&&metadata==='ok'" class="pagination"><button type="button" :disabled="disabled||busy||page<=1" @click="search(page-1)">上一页附魔</button><span>第 {{page}} 页</span><button type="button" :disabled="disabled||busy||!more" @click="search(page+1)">下一页附魔</button></div>
   <p class="field-hint">只列出PVF明确的附魔定义；部位按原文展示，未校验与当前装备的完整适用性。效果为原始数值，速度等未换算成百分比。</p>
  </details>
 </section>
</template>
<style scoped>
.enchantment-picker{padding:16px;border:1px solid var(--border-color);border-radius:12px;background:var(--bg-secondary);min-width:0}.enchantment-picker h4{margin:0}.enchantment-selection{margin:12px 0;overflow-wrap:anywhere}.enchantment-selection small{display:block;margin-top:6px;color:var(--text-secondary)}.enchantment-search{display:flex;align-items:end;gap:10px;margin:14px 0}.enchantment-search label{display:grid;gap:6px;flex:1;min-width:0}.enchantment-results{display:grid;gap:8px;margin:12px 0}.enchantment-results article{display:flex;gap:12px;align-items:center;padding:12px;border:1px solid var(--border-color);border-radius:10px;min-width:0}.enchantment-results article.is-selected{border-color:var(--primary-color)}.enchantment-results article>div{flex:1;min-width:0}.enchantment-results small{display:block;color:var(--text-secondary);margin-top:3px}.enchantment-results p{margin:4px 0 0;font-size:12px;overflow-wrap:anywhere}.enchantment-picker details>summary{cursor:pointer}.enchantment-results button{flex-shrink:0}@media(max-width:600px){.enchantment-search{flex-wrap:wrap}.enchantment-search label{flex-basis:100%}.enchantment-search>button{width:100%}.enchantment-results article{gap:8px;padding:9px}}
</style>
