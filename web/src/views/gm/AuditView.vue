<script setup lang="ts">
import {onMounted,onUnmounted,watch} from 'vue'
import {useRoute} from 'vue-router'
import {useGmWorkspace} from '../../stores/gm/useGmWorkspace'
import {useGmWorkspaceBindings} from '../../stores/gm/useGmWorkspace'
import {asyncPanel} from '../../asyncPanel'
import OperationResults from './OperationResults.vue'
import FieldError from '../../components/FieldError.vue'
const {fieldErrors,feedbackScope,busy,readBusy,error,page,search,rows,code,action,reason,message,actionNames,localTime,run,load,searchRows,inspectFromAudit}=useGmWorkspaceBindings()

const workspace=useGmWorkspace()
const route=useRoute()
function openLinked(){const id=String(route.query.operation_id||'');if(/^[a-f0-9]{32}$/.test(id))void inspectFromAudit(id)}
onMounted(async()=>{await workspace.activate('audit');openLinked()})
watch(()=>route.query.operation_id,openLinked)
onUnmounted(()=>workspace.cancelRead('list'))
</script>
<template><div class="gm-workspace"><section class="panel"><div class="section-title"><h2>审计流水</h2><span class="pill">只读 · 不可删除</span><a v-if="!search||/^[1-9]\d{0,9}$/.test(search)" :href="'/dnf-gm/api/v1/audit/export?uid='+(search||0)" download>导出筛选后的全部记录</a></div><form class="toolbar" @submit.prevent="searchRows"><input id="audit-uid" v-model="search" :aria-invalid="!!fieldErrors['audit-uid']" :aria-describedby="fieldErrors['audit-uid']?'audit-uid-error':undefined" aria-label="筛选 UID" placeholder="按目标 UID 筛选，留空查看全部" :disabled="busy"><button :disabled="busy">查询</button></form><FieldError id="audit-uid-error" :message="fieldErrors['audit-uid']"/><p v-if="error&&feedbackScope==='audit'" class="submit-error">{{error}}</p><div class="audit-list"><article v-for="r in rows" :key="r.id"><div class="audit-row"><span class="audit-dot"/><div class="audit-main"><div class="section-title"><h3>{{actionNames[r.action]||r.action}}</h3><time>{{localTime(r.created_at)}}</time></div><p>{{r.reason}}</p><small>操作人 {{r.actor||'admin'}} · 目标 UID {{r.target_uid??'—'}}</small><code>{{r.operation_id}}</code><details><summary>展开请求与结果</summary><pre>{{JSON.stringify(r,null,2)}}</pre></details></div><button v-if="r.action!=='gift-template'&&/^[a-f0-9]{32}$/.test(r.operation_id)" :disabled="busy" @click="inspectFromAudit(r.operation_id)">{{r.action==='mail'?'查询结果 / 邮件领取标记':'查询结果'}}</button></div></article><p v-if="!rows.length&&!busy&&!readBusy.list" class="empty">没有匹配的审计记录。</p></div><p v-if="readBusy.list" role="status" class="field-hint">正在查询审计记录…</p><div class="pagination"><button :disabled="page===1||busy||readBusy.list" @click="page--;load()">上一页</button><span>第 {{page}} 页</span><button :disabled="rows.length<50||busy||readBusy.list" @click="page++;load()">下一页</button></div></section><OperationResults v-if="!workspace.operationOpen"/></div></template>
