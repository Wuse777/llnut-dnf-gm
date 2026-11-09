<script setup lang="ts">
import scene from '@/assets/arad-guild-counter-v1.webp';
import sceneSmall from '@/assets/arad-guild-counter-mobile-v1.webp';

defineProps<{ eyebrow: string; title: string; description: string }>();
</script>

<template>
 <header class="gm-scene-banner">
  <picture aria-hidden="true"><source media="(max-width: 600px)" :srcset="sceneSmall"><img :src="scene" alt="" width="1672" height="941" decoding="async"></picture>
  <div class="gm-scene-copy"><span>{{eyebrow}}</span><h1>{{title}}</h1><p>{{description}}</p></div>
  <div v-if="$slots.default" class="gm-scene-action"><slot/></div>
 </header>
</template>

<style scoped>
.gm-scene-banner{position:relative;isolation:isolate;display:flex;align-items:center;justify-content:space-between;gap:24px;min-width:0;min-height:128px;margin-bottom:20px;padding:22px 26px;overflow:hidden;border:1px solid var(--border-color);border-radius:16px;background:var(--bg-primary)}
picture{position:absolute;inset:0 0 0 32%;z-index:-1;pointer-events:none;mask-image:linear-gradient(90deg,transparent,#000 60%);opacity:.38}
img{width:100%;height:100%;object-fit:cover;object-position:center 60%}
.gm-scene-copy{min-width:0;max-width:72%}.gm-scene-copy>span{font-size:10px;font-weight:600;letter-spacing:.14em;color:var(--primary-color)}
.gm-scene-copy h1{font-size:24px;line-height:1.4;font-weight:600;margin:5px 0;color:var(--text-primary)}
.gm-scene-copy p{margin:0;color:var(--text-secondary);font-size:13px;line-height:1.65}
.gm-scene-action{flex:none;position:relative}.gm-scene-action :slotted(button){box-shadow:0 4px 12px #1c28521a}
.dark .gm-scene-banner picture{opacity:.22}
@media(max-width:700px){.gm-scene-banner{min-height:112px;padding:18px;gap:12px;flex-wrap:wrap}.gm-scene-copy{max-width:100%}.gm-scene-copy h1{font-size:21px}.gm-scene-copy p{font-size:12px}picture{left:15%;opacity:.2}.gm-scene-action{width:100%}.gm-scene-action :slotted(button){font-size:12px;padding:8px 12px}}
</style>
