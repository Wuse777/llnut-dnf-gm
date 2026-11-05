<script setup lang="ts">
defineProps<{busy?:boolean}>()
const emit=defineEmits<{navigate:[target:string]}>()
</script>
<template>
 <section class="workbench-hero" aria-label="管理快捷入口">
  <div class="workbench-copy"><span class="workbench-kicker">DNF / GM WORKSPACE</span><h2>从一个玩家开始，<br>管理你的冒险世界。</h2><p>查询角色、整理奖励、追踪每一次操作。<br class="hero-line">在同一个工作台完成日常管理。</p><div class="workbench-actions"><button :disabled="busy" @click="emit('navigate','accounts')">查找玩家 <span aria-hidden="true">↗</span></button><button :disabled="busy" class="hero-secondary" @click="emit('navigate','mail')">准备奖励邮件</button></div></div>
  <!-- Original vector decoration, not a DNF item image or character portrait. -->
  <svg class="workbench-art" viewBox="0 0 440 300" fill="none" aria-hidden="true" focusable="false">
   <path d="M34 265H410M75 240H375M110 216H340" stroke="currentColor" opacity=".2"/>
   <path d="M118 215V119L223 28L328 119V215M138 215V127L223 54L308 127V215" stroke="currentColor" stroke-width="1.4"/>
   <path d="M156 215V135L223 78L290 135V215" stroke="currentColor" opacity=".4"/>
   <path d="M223 106L255 151L223 196L191 151Z" fill="currentColor" opacity=".12"/>
   <path d="M223 106L255 151L223 196L191 151ZM223 106V196M191 151H255" stroke="currentColor" stroke-width="1.6"/>
   <path d="M223 94V86M223 208V216M179 151H171M267 151H275M133 64L128 74L118 79L128 84L133 94L138 84L148 79L138 74ZM344 177L340 185L332 189L340 193L344 201L348 193L356 189L348 185Z" stroke="currentColor"/>
   <path d="M84 230L96 124L103 111L110 126L100 232M75 216L111 220M89 236L86 251M348 230L359 124L366 111L373 126L364 232M339 216L376 220M353 236L350 251" stroke="currentColor" stroke-width="1.5"/>
   <circle cx="223" cy="151" r="83" stroke="currentColor" stroke-dasharray="2 9" opacity=".25"/>
   <path d="M53 109H77M65 97V121M365 73H379M372 66V80" stroke="currentColor" opacity=".45"/>
  </svg>
 </section>
</template>
<style scoped>
.workbench-hero{position:relative;isolation:isolate;overflow:hidden;min-height:258px;border:1px solid #4d4840;border-radius:16px;padding:32px 36px;margin-bottom:24px;background:radial-gradient(ellipse at 83% 50%,#514336 0,transparent 53%),#242723;color:#f5f1e9;box-shadow:0 5px 20px #1517100a}.workbench-copy{position:relative;z-index:1;max-width:65%}.workbench-kicker{font-size:10px;font-weight:600;letter-spacing:.22em;color:#cfb58d}.workbench-copy h2{font-size:clamp(23px,2.4vw,31px);font-weight:600;letter-spacing:-.04em;line-height:1.4;margin:12px 0}.workbench-copy p{font-size:12px;line-height:1.9;color:#d0cbbf}.hero-line{display:none}.workbench-actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:20px}.workbench-actions button{font-size:12px;padding:10px 16px;background:#ddc49d;border-color:#ddc49d;color:#28281f}.workbench-actions button:hover:not(:disabled){background:#edd7b6}.workbench-actions .hero-secondary{background:transparent;color:#e4dccf;border-color:#756957}.workbench-actions .hero-secondary:hover:not(:disabled){background:#ffffff10}.workbench-art{position:absolute;right:10px;top:50%;width:43%;max-height:100%;transform:translateY(-50%);color:#d2af78;opacity:.85;pointer-events:none;transition:opacity 200ms ease}
@media(max-width:680px){.workbench-hero{padding:24px;min-height:260px;margin-bottom:16px}.workbench-copy{max-width:100%}.workbench-copy h2{font-size:24px}.workbench-copy p{max-width:80%}.hero-line{display:block}.workbench-art{right:-70px;width:270px;opacity:.22}.workbench-actions{gap:8px}.workbench-actions button{padding:10px 12px}.workbench-copy h2{max-width:90%}}
@media(prefers-reduced-motion:reduce){.workbench-art{transition:none}}
</style>
