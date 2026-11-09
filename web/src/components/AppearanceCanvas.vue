<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue';
import { acquireAtlases, clipAssets, frameAt } from '../appearance/renderer';
import { acquirePlayback } from '../appearance/playback';
import type { Appearance, AppearanceAction, Clip } from '../appearance/types';

const props = withDefaults(defineProps<{ appearance: Appearance; action: AppearanceAction; playing?: boolean; speed?: number; direction?: 'right' | 'mirror_left' }>(), { playing: true, speed: 1, direction: 'right' });
const emit = defineEmits<{ error: [message: string]; frame: [index: number, count: number]; paused: [] }>();
const canvas = ref<HTMLCanvasElement>();
const loading = ref(false);
const error = ref('');
const currentFrame = ref(0);
const frameCount = ref(0);
let controller: AbortController | undefined;
let lease: Awaited<ReturnType<typeof acquireAtlases>> | undefined;
let clip: Clip | undefined;
let raf = 0;
let active = true;
let visible = true;
let reduceMotion = false;
let started = 0;
let elapsed = 0;
let generation = 0;
let currentSpeed = props.speed;
let releasePlayback: (() => void) | undefined;
let media: MediaQueryList | undefined;
const paused = computed(() => !props.playing);

function draw(index: number): void {
  const context = canvas.value?.getContext('2d');
  if (!context || !clip || !lease) return;
  context.clearRect(0, 0, 512, 512);
  context.imageSmoothingEnabled = false;
  context.save();
  if (props.direction === 'mirror_left') { context.translate(512, 0); context.scale(-1, 1); }
  for (const draw of clip.frames[index]!.draws) {
    const page = lease.images.get(draw.atlas);
    if (page) context.drawImage(page, draw.sx, draw.sy, draw.width, draw.height, 256 + draw.x, 448 + draw.y, draw.width, draw.height);
  }
  context.restore();
  currentFrame.value = index + 1;
  emit('frame', index + 1, clip.frames.length);
}

function stop(): void {
  if (raf) { elapsed += (performance.now() - started) * currentSpeed; cancelAnimationFrame(raf); raf = 0; }
  releasePlayback?.(); releasePlayback = undefined;
}
function tick(now: number): void {
  if (!clip) return;
  const position = elapsed + (now - started) * currentSpeed;
  draw(frameAt(clip, position));
  if (!clip.loop && position >= clip.duration_ms) { elapsed = clip.duration_ms - 1; raf = 0; releasePlayback?.(); releasePlayback = undefined; emit('paused'); return; }
  raf = requestAnimationFrame(tick);
}
function resume(): void {
  if (!raf && clip && lease && active && visible && props.playing && !reduceMotion) {
    if (!clip.loop && elapsed >= clip.duration_ms - 1) elapsed = 0;
    currentSpeed = props.speed;
    releasePlayback = acquirePlayback(() => { stop(); emit('paused'); });
    started = performance.now(); raf = requestAnimationFrame(tick);
  }
}
function visibility(): void { visible = document.visibilityState !== 'hidden'; stop(); resume(); }
function motion(): void { reduceMotion = Boolean(media?.matches); stop(); resume(); }
function step(delta: number): void {
  stop();
  if (!clip) return;
  const target = (currentFrame.value - 1 + delta + clip.frames.length) % clip.frames.length;
  elapsed = clip.frames.slice(0, target).reduce((time, frame) => time + frame.duration_ms, 0);
  draw(target);
}
function release(): void { stop(); controller?.abort(); lease?.release(); lease = undefined; clip = undefined; }
async function load(): Promise<void> {
  const token = ++generation;
  release(); elapsed = 0; error.value = ''; loading.value = true;
  controller = new AbortController();
  try {
    const data = clipAssets(props.appearance, props.action);
    const acquired = await acquireAtlases(data.pages, controller.signal);
    if (token !== generation || !active) { acquired.release(); return; }
    lease = acquired; clip = data.clip; frameCount.value = clip.frames.length;
    draw(0); resume();
  } catch (cause) {
    if (token === generation && !controller?.signal.aborted) {
      error.value = cause instanceof Error ? cause.message : '角色图集暂不可用'; emit('error', error.value);
    }
  } finally { if (token === generation) loading.value = false; }
}
watch(() => [props.appearance, props.action], () => { if (active) void load(); });
watch(() => [props.playing, props.speed], () => { stop(); resume(); });
watch(() => props.direction, () => { if (clip) draw(Math.max(0, currentFrame.value - 1)); });
onMounted(() => {
  media = window.matchMedia('(prefers-reduced-motion: reduce)'); reduceMotion = media.matches;
  media.addEventListener('change', motion); document.addEventListener('visibilitychange', visibility);
  void load();
});
onActivated(() => { active = true; if (!lease && canvas.value) void load(); else resume(); });
onDeactivated(() => { active = false; ++generation; release(); });
onBeforeUnmount(() => { ++generation; release(); document.removeEventListener('visibilitychange', visibility); media?.removeEventListener('change', motion); });
defineExpose({ step });
</script>

<template>
  <div class="appearance-stage" :aria-busy="loading">
    <div class="appearance-stage__halo" aria-hidden="true"></div>
    <div class="appearance-stage__ground" aria-hidden="true"></div>
    <canvas ref="canvas" width="512" height="512" class="appearance-stage__canvas" aria-label="角色时装存档动作画布"></canvas>
    <div v-if="loading" class="appearance-stage__status" role="status">正在读取角色图集…</div>
    <div v-else-if="error" class="appearance-stage__status appearance-stage__status--error" role="alert">{{ error }}</div>
    <div v-else class="appearance-stage__caption"><span>{{ paused ? '静态帧' : '存档动作' }}</span><span>{{ currentFrame }} / {{ frameCount }}</span></div>
  </div>
</template>

<style scoped>
.appearance-stage { position:relative; isolation:isolate; width:100%; max-width:560px; aspect-ratio:1; margin:auto; overflow:hidden; border:1px solid #e2e8f4; border-radius:24px; background:linear-gradient(180deg,#f6f8ff 0%,#fafbfe 62%,#edf2fb 100%); }
.appearance-stage__canvas { position:relative; z-index:2; display:block; width:100%; height:100%; image-rendering:pixelated; }
.appearance-stage__halo { position:absolute; inset:14% 18% 20%; border-radius:50%; background:radial-gradient(ellipse,#dce5ff99,transparent 68%); }
.appearance-stage__ground { position:absolute; z-index:1; left:24%; right:24%; bottom:10%; height:6%; border:1px solid #d3dff2; border-radius:50%; background:radial-gradient(ellipse,#a6b5d44d,transparent 70%); }
.appearance-stage__status { position:absolute; z-index:3; inset:0; display:grid; place-items:center; padding:30px; color:#52617c; text-align:center; background:#f7f9ffe8; }
.appearance-stage__status--error { color:#a24a2d; }
.appearance-stage__caption { position:absolute; z-index:3; bottom:14px; left:18px; right:18px; display:flex; justify-content:space-between; color:#6b7992; font-size:12px; font-variant-numeric:tabular-nums; }
</style>
