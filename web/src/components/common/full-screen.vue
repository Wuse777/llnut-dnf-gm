<script setup lang="ts">
import { $t } from '@/locales';

defineOptions({
  name: 'FullScreen'
});

interface Props {
  full?: boolean;
}

defineProps<Props>();
</script>

<template>
  <ButtonIcon :key="String(full)" :tooltip-content="full ? $t('icon.fullscreenExit') : $t('icon.fullscreen')">
    <SvgIcon :icon="full ? 'ph:arrows-in' : 'ph:arrows-out'" />
  </ButtonIcon>
</template>

<style scoped></style>
