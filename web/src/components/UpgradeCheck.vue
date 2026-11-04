<script setup lang="ts">
import {ref,computed,onMounted,onBeforeUnmount} from 'vue'
import {api,ApiError,uncertainMessage} from '../api'
const emit=defineEmits(['expired','navigate','inspect'])
const data=ref<any>(null),page=ref<any>(null),busy=ref(false),error=ref(''),sectionError=ref(''),kind=ref('templates'),cursor=ref(''),history=ref<string[]>([])
const sourceNames:Record<string,string>={templates:'礼包全部版本',preferences:'收藏与最近物品',policies:'发放策略',schedules:'定时运营',jobs:'批量奖励任务',previews:'未提交预览',images:'当前图片映射',portraits:'职业头像映射'}
const capabilityNames:Record<string,string>={baseline:'当前运行基线',mail:'邮件发放',templates:'礼包引用',policies:'发放策略',assets:'图标与头像',schedules:'定时任务',inventory:'装备存档',currency:'账号货币',ban:'封禁',native:'公告／踢人／会话',unlock:'装备解锁',image:'候选镜像'}
const issues:Record<string,string>={saved_binding_unknown:'原操作未保存可核对的PVF绑定，须重新核对预览',saved_pvf_mismatch:'原操作保存的PVF指纹与候选版本不一致',saved_image_mismatch:'原计划保存的镜像绑定与候选声明不同',portrait_pack_missing:'未安装候选头像包',portrait_pvf_mismatch:'候选头像包PVF不匹配',portrait_mapping_missing:'候选包缺少这一精确职业／转职／性别映射（未把通配映射视为相同）',portrait_mapping_changed:'头像内容摘要变化，需核对实际图片',template_missing:'引用的礼包版本不存在',template_disabled:'引用的礼包已停用',template_version_old:'引用的礼包不是当前版本',pvf_bound_reference:'该引用绑定其他PVF，不会自动迁移',historical_pvf_unknown:'没有该历史PVF的索引，当前名称不作为历史名称',recreate_bound_operation:'指纹将变化，需核对并重建绑定操作；本检查不会暂停或执行任务',unreadable_reference:'引用文档缺失、过大或格式异常，不能判为无差异'}
const changes:Record<string,string>={candidate_policy_disabled:'候选PVF下已有手动停用策略',current_item_unknown:'当前物品基线未知',candidate_item_missing:'候选版本中找不到物品',name_changed:'名称变化',category_changed:'分类变化',level_changed:'等级变化',stack_limit_changed:'堆叠元数据变化（不限制发放数量）',durability_changed:'耐久元数据变化',source_path_changed:'PVF条目路径变化',mail_kind_changed:'邮件投递类型变化'}
const assetNames:Record<string,string>={not_installed:'未安装图片包',matched:'图片包指纹匹配（非像素验收）',mismatch:'图片包PVF不匹配',ready:'有可用映射记录（未检查像素）',missing:'缺少映射',missing_reference:'没有PVF图片引用',ambiguous:'来源冲突',unsupported:'格式待适配',unavailable:'不可用'}
const statusNames:Record<string,string>={active:'当前启用版',historical:'历史或停用版',favorite:'收藏',recent:'最近选择',enabled:'策略启用',disabled:'策略停用',preview:'待确认',running:'运行中',paused:'已暂停',cancelled:'已取消',finished:'已完成',completed:'已完成',ready:'已解析映射',missing:'缺少素材',unsupported:'待适配'}
const destination=computed(() => ({templates:'gifts',preferences:'catalog',policies:'catalog',schedules:'schedules',jobs:'reward-jobs',previews:'audit',images:'catalog',portraits:'accounts'} as Record<string,string>)[kind.value])
const exportHref=computed(()=>data.value?.fingerprint?'/dnf-gm/api/v1/compatibility/export?fingerprint='+data.value.fingerprint:'')
let alive=true,generation=0
function fail(e:unknown,section=false){if(e instanceof ApiError&&e.status===401)emit('expired');if(section)sectionError.value=uncertainMessage(e);else error.value=uncertainMessage(e)}
async function load(){
 if(busy.value)return
 const n=++generation;busy.value=true;error.value='';sectionError.value='';data.value=null;page.value=null;history.value=[];cursor.value=''
 try{const result=await api('/compatibility');if(alive&&n===generation)data.value=result}catch(e){if(alive&&n===generation)fail(e)}finally{if(alive&&n===generation)busy.value=false}
 if(alive&&n===generation&&data.value?.state==='ready')await readPage()
}
async function readPage(){
 if(busy.value||data.value?.state!=='ready')return
 const n=generation;busy.value=true;sectionError.value='';page.value=null
 try{const result=await api('/compatibility/references?'+new URLSearchParams({kind:kind.value,fingerprint:data.value.fingerprint,cursor:cursor.value}));if(alive&&n===generation)page.value=result}catch(e){if(alive&&n===generation)fail(e,true)}finally{if(alive&&n===generation)busy.value=false}
}
async function choose(value:string){if(busy.value)return;kind.value=value;cursor.value='';history.value=[];await readPage()}
async function next(){if(busy.value||!page.value?.next_cursor)return;history.value.push(cursor.value);cursor.value=page.value.next_cursor;await readPage()}
async function previous(){if(busy.value||!history.value.length)return;cursor.value=history.value.pop()!;await readPage()}
onMounted(load);onBeforeUnmount(()=>{alive=false;generation++})
</script>
<template><section class="upgrade-check">
 <header class="section-title"><div><h2>升级兼容性检查</h2><p class="muted">比较离线候选版本与已保存引用。不会替换当前PVF、修改礼包、暂停任务或重启服务。</p></div><button :disabled="busy" @click="load">重新检查基线</button></header>
 <p v-if="error" class="submit-error" role="alert">{{error}}</p><p v-if="busy" role="status">正在读取检查数据…</p>
 <p v-if="data?.state==='not_configured'" class="notice">{{data.message}} 请维护人员准备候选索引和可选图片包；网页不接收PVF上传。</p>
 <template v-if="data?.state==='ready'">
 <p class="notice">{{data.note}}</p><p v-if="!data.current.live_aligned" class="warning" role="alert">当前运行指纹未确认一致，不能把下面的静态比较当作已确认的生产升级基线。</p>
 <div class="upgrade-versions"><article class="panel"><h3>当前配置与索引</h3><p>PVF <code>{{data.current.pvf_sha256}}</code></p><p>镜像 <code>{{data.current.configured_image||'未知'}}</code></p><p>图片：{{assetNames[data.assets.current.state]||'未知'}}</p></article><article class="panel"><h3>候选版本（未激活）</h3><p>PVF <code>{{data.candidate.pvf_sha256}}</code></p><p>声明的镜像 <code>{{data.candidate.declared_image||'未提供，只比较索引'}}</code></p><p>图片：{{assetNames[data.assets.candidate.state]||'未知'}}</p><small>镜像摘要仅为维护配置声明，未拉取或验证候选镜像内部结构。</small></article></div>
 <section class="panel"><h3>需要复验的能力</h3><p v-if="!data.recheck.length">未发现指纹变更；这不是游戏内兼容性验收，也不是发布许可。</p><ul><li v-for="(r,i) in data.recheck" :key="r.capability+':'+i"><b>{{capabilityNames[r.capability]||r.capability}}</b>：{{r.reason}}</li></ul><p class="field-hint">{{data.scope}}</p></section>
 <section class="panel"><div class="section-title"><h3>已保存引用检查</h3><a :href="exportHref" download>导出全部引用报告（NDJSON）</a></div><p class="field-hint">界面每页50条，不代表全量已检查。导出使用独立一致性快照；末行必须有 complete 才表示引用遍历完成，仍不代表可以直接部署。</p>
 <div class="upgrade-tabs" role="group" aria-label="引用类型"><button v-for="source in data.sources" :key="source" :disabled="busy" :aria-pressed="kind===source" @click="choose(source)">{{sourceNames[source]||source}}</button></div>
 <div class="section-title"><p>第 {{history.length+1}} 页 · {{sourceNames[kind]}}</p><button :disabled="busy" @click="emit('navigate',destination)">前往对应管理页面</button></div>
 <p v-if="sectionError" class="submit-error" role="alert">{{sectionError}} <button :disabled="busy" @click="readPage">重试本页</button> 若目标已变，请点击上方“重新检查基线”。</p>
 <template v-if="page"><p v-if="!page.items.length" class="empty">本次查询没有引用记录；未安装图片包时没有图片条目，不代表素材已验证。</p>
 <article v-for="row in page.items" :key="row.id" class="upgrade-reference"><div class="section-title"><b>{{row.label}}</b><span>{{statusNames[row.status]||row.status}}</span></div><code>{{row.id}}</code><p :class="row.needs_review?'warning':'field-hint'">{{row.needs_review?'引用需要核对':'本项未检出引用差异（不是游戏效果验收）'}}</p><p v-if="row.template">引用礼包 #{{row.template.id}} · v{{row.template.version}}</p><ul v-if="row.issues.length"><li v-for="issue in row.issues" :key="issue">{{issues[issue]||issue}}</li></ul>
 <div v-for="item in row.items" :key="item.id" class="upgrade-item"><b>#{{item.id}} · {{item.after?.name||item.before?.name||'物品未知'}}</b><p>当前：{{item.before?.name||'未确认'}} → 候选：{{item.after?.name||'不存在'}}</p><ul v-if="item.changes.length"><li v-for="change in item.changes" :key="change">{{changes[change]||change}}</li></ul><p>候选图标：{{assetNames[item.candidate_image_state]||'未知状态'}}</p><details><summary>查看索引属性对照</summary><div class="upgrade-comparison"><div><b>当前索引</b><pre>{{JSON.stringify(item.before,null,2)}}</pre></div><div><b>候选索引</b><pre>{{JSON.stringify(item.after,null,2)}}</pre></div></div></details></div>
 <p class="field-hint">{{row.note}}</p><button v-if="kind==='previews'" @click="emit('inspect',row.id)">查询原操作，不执行</button></article>
 <p class="field-hint">{{page.scope_note}}</p></template>
 <div class="pagination"><button :disabled="busy||!history.length" @click="previous">上一页引用</button><button :disabled="busy||!page?.next_cursor" @click="next">下一页引用</button></div></section>
 </template>
</section></template>
<style scoped>
.upgrade-check{display:grid;gap:20px}.upgrade-check a{color:var(--text-primary);text-underline-offset:3px}.upgrade-check .section-title{gap:12px;flex-wrap:wrap}.upgrade-versions,.upgrade-comparison{display:grid;grid-template-columns:1fr 1fr;gap:16px;min-width:0}.upgrade-versions article{min-width:0}.upgrade-versions code{display:block;margin-top:6px}.upgrade-check code,.upgrade-reference b{overflow-wrap:anywhere}.upgrade-tabs{display:flex;flex-wrap:wrap;gap:8px}.upgrade-tabs [aria-pressed=true]{outline:1px solid var(--border-color);background:var(--bg-primary)}.upgrade-reference{padding:20px 0;border-top:1px solid var(--border-color)}.upgrade-item{padding:12px;margin:10px 0;border:1px solid var(--border-color);border-radius:8px}.upgrade-item p{margin:8px 0}.upgrade-check pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}.upgrade-check li{margin:8px 0;overflow-wrap:anywhere}.upgrade-comparison>div{min-width:0}@media(max-width:600px){.upgrade-versions,.upgrade-comparison{grid-template-columns:1fr}.upgrade-tabs button{flex:1 1 135px}.upgrade-check header>button{width:100%}}
</style>
