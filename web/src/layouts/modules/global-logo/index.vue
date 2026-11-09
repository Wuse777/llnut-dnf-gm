<script setup lang="ts">
defineOptions({
  name: 'GlobalLogo'
});

interface Props {
  /** Whether to show the title */
  showTitle?: boolean;
}

withDefaults(defineProps<Props>(), {
  showTitle: true
});
</script>

<template>
  <RouterLink to="/" class="gm-global-logo w-full flex-center nowrap-hidden">
    <SystemLogo class="size-30px gm-brand-accent" />
    <div v-show="showTitle" class="pl-9px transition duration-300 ease-in-out">
      <h2 class="text-17px font-bold tracking-1px">DNF <span class="gm-brand-accent">GM</span></h2>
      <span class="block text-9px tracking-2px opacity-45">阿拉德管理工作台</span>
    </div>
  </RouterLink>
</template>

<style scoped>
.gm-brand-accent{color:var(--gm-accent-color,#92651f)}
.bg-inverted .gm-brand-accent{color:var(--gm-inverted-accent,#d4ad66)}
</style>
