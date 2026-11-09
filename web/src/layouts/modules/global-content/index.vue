<script setup lang="ts">
import { computed, onUnmounted, watch } from 'vue';
import { usePreferredReducedMotion } from '@vueuse/core';
import { LAYOUT_SCROLL_EL_ID } from '@sa/materials';
import { useAppStore } from '@/store/modules/app';
import { useTabStore } from '@/store/modules/tab';
import { useThemeStore } from '@/store/modules/theme';

defineOptions({
  name: 'GlobalContent'
});

interface Props {
  /** Show padding for content */
  showPadding?: boolean;
}

withDefaults(defineProps<Props>(), {
  showPadding: true
});

const appStore = useAppStore();
const themeStore = useThemeStore();
const tabStore = useTabStore();

const reducedMotion = usePreferredReducedMotion();
// Previously saved modes remain valid preferences, with a short entry fade only.
const animateEntry = computed(() => themeStore.page.animate && themeStore.page.animateMode !== 'none' && reducedMotion.value !== 'reduce');
const entering = new Map<Element, Animation>();

function resetScroll() {
  const el = document.querySelector(`#${LAYOUT_SCROLL_EL_ID}`);

  el?.scrollTo({ left: 0, top: 0 });
}

function cancelEntry(element: Element) {
  const animation = entering.get(element);
  entering.delete(element);
  animation?.cancel();
}

function enterPage(element: Element, done: () => void) {
  resetScroll();
  appStore.setContentXScrollable(false);
  if (!animateEntry.value || typeof element.animate !== 'function') {
    done();
    return;
  }
  try {
    const animation = element.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 100, easing: 'ease-out' });
    entering.set(element, animation);
    const finish = () => {
      if (entering.get(element) === animation) entering.delete(element);
      done();
    };
    void animation.finished.then(finish, finish);
  } catch {
    // An unsupported animation must never hold navigation open.
    done();
  }
}

function leavePage(element: Element, done: () => void) {
  cancelEntry(element);
  // Synchronous removal keeps player/write forms unique and adds no exit delay.
  done();
}

function cancelAllEntries() {
  for (const element of entering.keys()) cancelEntry(element);
}

watch(animateEntry, enabled => { if (!enabled) cancelAllEntries(); });
onUnmounted(cancelAllEntries);
</script>

<template>
  <RouterView v-slot="{ Component, route }">
    <Transition
      :css="false"
      @enter="enterPage"
      @leave="leavePage"
      @enter-cancelled="cancelEntry"
    >
      <component
        :is="Component"
        v-if="appStore.reloadFlag"
        :key="tabStore.getTabIdByRoute(route)"
        :class="{ 'p-16px': showPadding }"
        class="gm-page flex-grow bg-layout"
      />
    </Transition>
  </RouterView>
</template>

<style></style>

