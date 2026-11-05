<script setup lang="ts">
import town from '../assets/town-dusk.webp'
import townSmall from '../assets/town-dusk-small.webp'
defineProps<{busy?:boolean}>()
const emit=defineEmits<{navigate:[target:string]}>()
</script>
<template>
 <section class="workbench-hero" aria-label="管理快捷入口">
  <div class="workbench-copy"><span class="workbench-kicker">DNF / GM WORKSPACE</span><h2>从一个玩家开始，<br>管理你的冒险世界。</h2><p>查询角色、整理奖励、追踪每一次操作。<br class="hero-line">在同一个工作台完成日常管理。</p><div class="workbench-actions"><button :disabled="busy" @click="emit('navigate','accounts')">查找玩家 <span aria-hidden="true">↗</span></button><button :disabled="busy" class="hero-secondary" @click="emit('navigate','mail')">准备奖励邮件</button></div></div>
  <img class="workbench-landscape" :src="town" :srcset="`${townSmall} 800w, ${town} 1600w`" sizes="(max-width: 768px) 100vw, 80vw" width="1600" height="534" alt="" aria-hidden="true" decoding="async">
  <span class="workbench-shade" aria-hidden="true"/>
 </section>
</template>
<style scoped>
.workbench-hero{position:relative;isolation:isolate;overflow:hidden;min-height:258px;border:1px solid #4d4840;border-radius:16px;padding:32px 36px;margin-bottom:24px;background:radial-gradient(ellipse at 83% 50%,#514336 0,transparent 53%),#242723;color:#f5f1e9;box-shadow:0 5px 20px #1517100a}.workbench-copy{position:relative;z-index:2;max-width:65%}.workbench-kicker{font-size:10px;font-weight:600;letter-spacing:.22em;color:#cfb58d}.workbench-copy h2{font-size:clamp(23px,2.4vw,31px);font-weight:600;letter-spacing:-.04em;line-height:1.4;margin:12px 0}.workbench-copy p{font-size:12px;line-height:1.9;color:#d0cbbf}.hero-line{display:none}.workbench-actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:20px}.workbench-actions button{font-size:12px;padding:10px 16px;background:#ddc49d;border-color:#ddc49d;color:#28281f}.workbench-actions button:hover:not(:disabled){background:#edd7b6}.workbench-actions .hero-secondary{background:transparent;color:#e4dccf;border-color:#756957}.workbench-actions .hero-secondary:hover:not(:disabled){background:#ffffff10}
@media(max-width:680px){.workbench-hero{padding:24px;min-height:260px;margin-bottom:16px}.workbench-copy{max-width:100%}.workbench-copy h2{font-size:24px}.workbench-copy p{max-width:80%}.hero-line{display:block}.workbench-actions{gap:8px}.workbench-actions button{padding:10px 12px}.workbench-copy h2{max-width:90%}}
.workbench-landscape{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;object-position:center;pointer-events:none;z-index:0}.workbench-shade{position:absolute;inset:0;background:linear-gradient(90deg,#101a25b8,transparent 90%);z-index:1;pointer-events:none}.workbench-actions .hero-secondary{background:#172331a6;border-color:#a4aeb8;color:#fff}
@media(max-width:680px){.workbench-landscape{object-position:72% center}.workbench-shade{background:#101a25bf}}
</style>
