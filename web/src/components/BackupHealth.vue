<script setup lang="ts">
import {onMounted,onUnmounted,ref} from 'vue'
import {api} from '../api'
const data=ref<any>(null),busy=ref(false),error=ref('')
let alive=true,timer:ReturnType<typeof setInterval>|undefined
const names:Record<string,string>={recent:'在时效内',overdue:'超过建议核验周期',not_recorded:'没有恢复演练记录',unverified:'恢复证据无效或核对失败',other_artifact:'演练针对另一份备份，不能证明当前备份可恢复'}
function date(n:any){return typeof n==='number'?new Date(n*1000).toLocaleString():'未记录'}
async function load(){if(busy.value)return;busy.value=true;error.value='';try{const d=await api('/backup-health');if(alive)data.value=d}catch(e:any){if(alive){data.value=null;error.value=e.message||'备份证据读取失败'}}finally{if(alive)busy.value=false}}
onMounted(()=>{void load();timer=setInterval(()=>{if(!document.hidden)void load()},30000)})
onUnmounted(()=>{alive=false;if(timer)clearInterval(timer)})
</script>
<template><section class="panel backup-health" aria-labelledby="backup-health-title"><div class="backup-heading"><h2 id="backup-health-title">备份与恢复健康</h2><button :disabled="busy" @click="load">{{busy?'正在核对备份…':'刷新备份证据'}}</button></div>
<p class="warning">此处只核验 GM 管理库，不包含游戏存档、服务器配置、PVF或图片包。备份文件存在不等于可恢复；恢复演练不会操作生产数据库。</p>
<p v-if="error" class="submit-error" role="alert">{{error}}</p>
<template v-if="data">
 <p v-if="data.state==='unavailable'" class="warning">尚无可读取的维护证据，无法判断备份是否成功。</p>
 <p v-else-if="data.state==='stale'" class="warning">备份证据已过期（超过24小时未重新核对文件）。最后核对 {{date(data.checked_at)}}；不能沿用旧值判断当前可恢复。</p>
 <p v-else-if="data.state==='integrity_failed'" class="warning">备份文件或收据校验失败／不可读，请维护者核对原始私有文件。没有标记为可恢复。</p>
 <template v-else-if="data.state==='ok'">
  <p class="field-hint">文件最后核对 {{date(data.checked_at)}} · 建议备份周期 {{data.policy.backup_hours}}小时，匹配备份的恢复演练周期 {{data.policy.restore_days}}天。</p>
  <div class="backup-cards"><article><h3>管理库备份</h3><p :class="data.backup.state==='recent'?'':'warning'">{{names[data.backup.state]||'未知'}}</p><p>完成 {{date(data.backup.completed_at)}}</p><p>{{data.backup.tables}} 张表 · {{data.backup.rows}} 行 · {{(data.backup.bytes/1048576).toFixed(2)}} MiB</p><details><summary>备份 SHA-256</summary><code>{{data.backup.artifact_sha256}}</code></details></article>
  <article><h3>隔离恢复演练</h3><p :class="data.restore.state==='recent'?'':'warning'">{{names[data.restore.state]||'未知'}}</p><p>完成 {{date(data.restore.completed_at)}}</p><p v-if="data.restore.state==='recent'||data.restore.state==='overdue'">已实际恢复这份备份，并核对表定义、行数和完整字段值摘要；临时库已清理。</p><p v-else>尚不能证明当前这份备份已通过恢复验证。</p></article></div>
 </template>
</template>
<p class="field-hint">此页面只读，不下载含凭据的备份，不提供生产整库覆盖或任意SQL入口。备份、隔离恢复和证据更新由维护工具执行。</p>
</section></template>
<style scoped>
.backup-heading{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}.backup-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,260px),1fr));gap:16px}.backup-cards article{border:1px solid var(--border-color);border-radius:10px;padding:16px;min-width:0}.backup-health p{margin:10px 0;overflow-wrap:anywhere}.backup-health code{display:block;overflow-wrap:anywhere;margin-top:8px}
</style>
