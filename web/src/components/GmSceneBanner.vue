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
.gm-scene-banner{position:relative;isolation:isolate;display:flex;align-items:center;justify-content:space-between;gap:20px;min-width:0;min-height:88px;margin-bottom:16px;padding:14px 18px;overflow:hidden;border:1px solid var(--border-color);border-radius:10px;background:var(--bg-primary)}
picture{position:absolute;inset:0 0 0 32%;z-index:-1;pointer-events:none;mask-image:linear-gradient(90deg,transparent,#000 60%);opacity:.38}
img{width:100%;height:100%;object-fit:cover;object-position:center 60%}
.gm-scene-copy{min-width:0;max-width:72%}.gm-scene-copy>span{font-size:10px;font-weight:600;letter-spacing:.14em;color:var(--primary-color)}
.gm-scene-copy h1{font-size:21px;line-height:1.4;font-weight:600;margin:2px 0 4px;color:var(--text-primary)}
.gm-scene-copy p{margin:0;color:var(--text-secondary);font-size:13px;line-height:1.65}
.gm-scene-action{flex:none;position:relative}.gm-scene-action :slotted(button){box-shadow:0 4px 12px #1c28521a}
.dark .gm-scene-banner picture{opacity:.22}
@media(max-width:700px){.gm-scene-banner{min-height:48px;padding:10px 12px;gap:8px;flex-wrap:wrap;margin-bottom:12px}.gm-scene-copy{max-width:100%}.gm-scene-copy h1{font-size:16px;margin:0}.gm-scene-copy>span,.gm-scene-copy p,picture{display:none}.gm-scene-action{margin-left:auto;max-width:100%}.gm-scene-action :slotted(button){font-size:12px;padding:6px 9px;white-space:normal}}
</style>
