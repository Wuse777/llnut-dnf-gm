<script setup lang="ts">
defineOptions({ name: 'DarkModeContainer' });

interface Props {
  inverted?: boolean;
}

defineProps<Props>();
</script>

<template>
  <div class="transition-300" :class="inverted ? 'gm-inverted-container bg-inverted' : 'bg-container text-base-text'">
    <slot></slot>
  </div>
</template>

<style scoped>
.gm-inverted-container{color:#e8e5df}
</style>
