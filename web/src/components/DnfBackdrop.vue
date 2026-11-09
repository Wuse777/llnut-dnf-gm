<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { api } from '@/api';
import { useGmPreferencesStore } from '@/store/modules/gm-preferences';
const prefs = useGmPreferencesStore();
const image = ref<{ url: string; name: string; focus: string } | null>(null);
const failed = ref(false);
let alive = true;
const visible = computed(() => prefs.showJobArt && image.value && !failed.value);
onMounted(async () => {
  try {
    const result = await api('/assets/coverage?state=missing&page=1');
    const portrait = result.portraits?.find((item: any) => item.image?.state === 'ready' &&
      /^\/dnf-gm\/api\/v1\/assets\/[a-f0-9]{64}\/[a-f0-9]{64}\.png$/.test(item.image.url ?? ''));
    if (alive && portrait) {
      const x = Number(portrait.image.focus_x), y = Number(portrait.image.focus_y);
      image.value = { url: portrait.image.url, name: portrait.name,
        focus: `${Number.isFinite(x) ? Math.max(0, Math.min(100, x)) : 50}% ${Number.isFinite(y) ? Math.max(0, Math.min(100, y)) : 25}%` };
    }
  } catch { /* Decorative art falls back to the original vector crest. */ }
});
onUnmounted(() => { alive = false; });
</script>

<template>
  <div class="dnf-backdrop" aria-hidden="true">
    <span class="dnf-backdrop-wordmark">ARAD<span>ADVENTURER OPERATIONS</span></span>
    <SystemLogo class="dnf-backdrop-crest" />
    <img v-if="visible" :src="image!.url" alt="" decoding="async" :style="{ objectPosition: image!.focus }" @error="failed = true" />
    <span class="dnf-backdrop-fade"></span>
    <span v-if="visible" class="dnf-art-caption">{{ image!.name }} · 职业插画</span>
  </div>
</template>

<style scoped>
.dnf-backdrop{position:absolute;inset:0;pointer-events:none;overflow:hidden;border-radius:inherit;background:linear-gradient(115deg,transparent 35%,#f1f1ff 77%,#ececfa)}.dnf-backdrop-wordmark{position:absolute;right:34px;top:38px;font-size:68px;line-height:1;font-weight:900;letter-spacing:9px;color:#6667a8;opacity:.1}.dnf-backdrop-wordmark span{display:block;font-size:9px;letter-spacing:3px;margin-top:12px}.dnf-backdrop-crest{position:absolute;height:250px;width:250px;right:20px;top:-30px;color:#7773c2;opacity:.12;transform:rotate(12deg)}.dnf-backdrop img{position:absolute;right:-15px;top:0;height:100%;width:45%;object-fit:cover;opacity:.45;mask-image:linear-gradient(to right,transparent,#000 48%);-webkit-mask-image:linear-gradient(to right,transparent,#000 48%)}.dnf-backdrop-fade{position:absolute;inset:0;background:linear-gradient(to right,var(--bg-primary,#fff),transparent 100%);opacity:.62}.dnf-art-caption{position:absolute;right:12px;bottom:8px;font-size:9px;color:#77758e;opacity:.8}.dark .dnf-backdrop{background:linear-gradient(115deg,transparent 35%,#24233a 77%,#302d48)}.dark .dnf-backdrop-fade{background:linear-gradient(to right,#1d1e26,transparent)}@media(max-width:600px){.dnf-backdrop img{display:none}.dnf-art-caption{display:none}.dnf-backdrop-wordmark{right:-5px;top:30px;font-size:52px}.dnf-backdrop-crest{right:-50px}}
</style>

