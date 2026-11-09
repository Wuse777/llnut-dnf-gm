<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { api, uncertainMessage } from '../api';
import type { Appearance, AppearanceAction, AppearancePreset } from '../appearance/types';
import AppearanceCanvas from './AppearanceCanvas.vue';

const props = defineProps<{ detail: any; initialRecipe?: AppearancePreset }>();
const emit = defineEmits<{ save: [recipe: AppearancePreset] }>();
const fitting = ref<Appearance>();
const fittingRecipe = ref<AppearancePreset>();
const action = ref<AppearanceAction>('idle');
const playing = ref(true);
const direction = ref<'right' | 'mirror_left'>('right');
const busy = ref(false);
const error = ref('');
const canvas = ref<InstanceType<typeof AppearanceCanvas>>();
const appearance = computed<Appearance | undefined>(() => fitting.value || props.detail?.appearance);
const actions: { value: AppearanceAction; label: string }[] = [{ value: 'idle', label: '待机' }, { value: 'walk', label: '行走' }, { value: 'attack', label: '普通攻击片段' }];
const available = computed(() => actions.filter(item => appearance.value?.actions?.[item.value]));
const canDraw = computed(() => available.value.length > 0);
const title = computed(() => fitting.value ? '本地试衣' : '时装存档');
const slotNames: Record<string, string> = { '[hat avatar]':'帽子','[hair avatar]':'头发','[face avatar]':'脸部','[breast avatar]':'胸部','[coat avatar]':'上衣','[skin avatar]':'皮肤','[waist avatar]':'腰部','[pants avatar]':'下装','[shoes avatar]':'鞋' };
const preset = computed<AppearancePreset | undefined>(() => {
  if (fittingRecipe.value) return { ...fittingRecipe.value, animation: action.value, direction: direction.value };
  const recipe = appearance.value?.recipe;
  if (!recipe) return undefined;
  return { job: recipe.job, grow_type: recipe.grow_type, sex: props.detail?.character?.sex ?? -1,
    slots: recipe.items.map(item => ({ slot: item.slot, item_id: item.id })), direction: direction.value, animation: action.value };
});
let request = 0;
async function apply(recipe: AppearancePreset): Promise<void> {
  const fingerprint = props.detail?.appearance?.pvf_sha256;
  if (!fingerprint) { error.value = '当前PVF指纹不可用，请刷新角色资料'; return; }
  const token = ++request; busy.value = true; error.value = '';
  try {
    const result = await api('/appearance/preview', 'POST', { ...recipe, pvf_sha256: fingerprint });
    if (token !== request) return;
    fitting.value = result; fittingRecipe.value = recipe; action.value = recipe.animation || 'idle'; direction.value = recipe.direction || 'right';
  } catch (cause) { if (token === request) error.value = uncertainMessage(cause); }
  finally { if (token === request) busy.value = false; }
}
function reset(): void { ++request; busy.value = false; fitting.value = undefined; fittingRecipe.value = undefined; error.value = ''; action.value = 'idle'; }
watch(() => props.initialRecipe, value => { if (value) void apply(value); }, { immediate: true, deep: true });
watch(() => props.detail?.character?.charac_no, () => reset());
watch(available, value => { if (!value.some(item => item.value === action.value)) action.value = value[0]?.value || 'idle'; });
defineExpose({ apply });
</script>

<template>
  <section class="appearance-workspace" aria-label="角色外观工作区">
    <div class="appearance-workspace__heading">
      <div><span class="appearance-eyebrow">CHARACTER APPEARANCE</span><h3>{{ title }}</h3><p>{{ appearance?.note || '读取角色资料后查看当前外观覆盖情况' }}</p></div>
      <span class="appearance-badge">{{ fitting ? '仅本地预览' : appearance?.complete ? '覆盖完整' : '部分覆盖' }}</span>
    </div>
    <p v-if="error" class="appearance-warning" role="alert">{{ error }}</p>
    <div class="appearance-workspace__grid">
      <div class="appearance-preview">
        <div v-if="canDraw && appearance" class="appearance-actions" aria-label="动作选择">
          <button v-for="item in actions" :key="item.value" type="button" :disabled="!appearance.actions[item.value] || busy" :class="{ selected: action === item.value }" :aria-pressed="action === item.value" @click="action = item.value">{{ item.label }}</button>
        </div>
        <AppearanceCanvas v-if="canDraw && appearance" ref="canvas" :appearance="appearance" :action="action" :playing="playing" :direction="direction" @paused="playing = false" @error="message => error = message" />
        <div v-else class="appearance-empty"><span aria-hidden="true">◇</span><strong>当前外观暂不可绘制</strong><p>保留装备与时装存档。缺少的规则或素材确认后，才能显示对应角色。</p></div>
        <div class="appearance-toolbar">
          <template v-if="canDraw"><button type="button" @click="playing = !playing">{{ playing ? '暂停' : '播放' }}</button><button type="button" @click="playing = false; canvas?.step(1)">下一帧</button><button type="button" :aria-pressed="direction === 'mirror_left'" @click="direction = direction === 'right' ? 'mirror_left' : 'right'">{{ direction === 'right' ? '原始方向' : '左向（镜像）' }}</button></template>
          <button v-if="fitting" type="button" @click="reset">返回实际存档</button>
          <button v-if="preset" type="button" class="appearance-primary" :disabled="busy" @click="emit('save', preset!)">保存为外观方案</button>
        </div>
        <small>动作在画布中原地展示。窗口隐藏时暂停；系统减少动态效果设置会停在静态帧。</small>
      </div>
      <div class="appearance-information">
        <div class="appearance-card"><h4>{{ fitting ? '试衣部件' : '实际显示的时装部件' }}</h4>
          <div v-if="appearance?.recipe?.items?.length" class="appearance-parts"><div v-for="item in appearance.recipe.items" :key="item.slot"><span>{{ slotNames[item.slot] || item.slot }}</span><code>#{{ item.id }}</code></div></div>
          <p v-else-if="appearance?.recipe">{{ fitting ? '当前方案未选择时装，预览使用默认部件。' : '当前没有穿戴时装，预览使用对应职业的默认部件。' }}</p>
          <p v-else>当前存档的时装身份尚不可确认。</p>
        </div>
        <div class="appearance-card"><h4>覆盖清单</h4>
          <div v-for="entry in appearance?.coverage || []" :key="entry.component" class="appearance-coverage"><span :class="entry.state === 'ready' ? 'appearance-dot--ready' : 'appearance-dot--pending'" class="appearance-dot" aria-hidden="true"></span><p>{{ entry.note }}</p><span>{{ entry.state === 'ready' ? '已支持' : '待适配' }}</span></div>
          <p v-for="reason in appearance?.reasons || []" :key="reason" class="appearance-reason">{{ reason }}</p>
          <p v-if="!appearance?.coverage?.length && !appearance?.reasons?.length">尚未安装外观部件包。</p>
        </div>
        <p class="appearance-footnote">客户端素材为私有安装内容。图片可解码不等于已通过游戏内视觉对照。</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.appearance-workspace { width:100%; color:#26334d; }
.appearance-workspace__heading { display:flex; align-items:flex-start; justify-content:space-between; gap:20px; margin-bottom:24px; }
.appearance-eyebrow { font-size:10px; font-weight:700; letter-spacing:.14em; color:#7789ac; }
h3 { margin:6px 0; font-size:25px; line-height:1.35; letter-spacing:-.03em; } p { margin:0; line-height:1.7; } h4 { margin:0 0 18px; font-size:14px; font-weight:650; }
.appearance-workspace__heading p,.appearance-card>p { color:#748098; font-size:13px; max-width:760px; }
.appearance-badge { flex-shrink:0; padding:6px 11px; border:1px solid #d8e4fb; border-radius:8px; color:#5279be; background:#f0f5ff; font-size:12px; }
.appearance-workspace__grid { display:grid; grid-template-columns:minmax(280px,1.12fr) minmax(260px,1fr); gap:28px; align-items:start; }
.appearance-actions { display:flex; gap:6px; margin-bottom:14px; padding:5px; border:1px solid #e5eaf5; border-radius:12px; background:#f7f9fd; }
button { border:1px solid #dce4f1; border-radius:8px; background:white; color:#526582; padding:8px 13px; font:inherit; font-size:13px; cursor:pointer; transition:background .15s; }
button:hover { background:#edf3ff; } button:focus-visible { outline:2px solid #6a8cef; outline-offset:2px; } button:disabled { opacity:.4; cursor:not-allowed; }
.appearance-actions button { flex:1; border-color:transparent; background:transparent; padding:8px 4px; white-space:nowrap; }.appearance-actions button.selected { background:white; color:#4f6fdf; box-shadow:0 2px 8px #687caa12; }
.appearance-toolbar { display:flex; flex-wrap:wrap; gap:8px; margin:16px 0 9px; }.appearance-primary { margin-left:auto; color:white; border-color:#5877df; background:#5877df; }.appearance-primary:hover { background:#4565cc; }
small,.appearance-footnote { color:#8a96ab; font-size:11px; line-height:1.8; }
.appearance-information { display:grid; gap:18px; }.appearance-card { padding:22px; border:1px solid #e7ebf4; border-radius:16px; background:white; }
.appearance-parts { display:grid; grid-template-columns:1fr 1fr; gap:8px 16px; }.appearance-parts>div { display:flex; justify-content:space-between; padding:7px 0; border-bottom:1px solid #f1f3f8; font-size:12px; }.appearance-parts span { color:#7c89a0; }code { color:#4c5d7d; font-size:11px; }
.appearance-coverage { display:flex; gap:9px; align-items:baseline; padding:9px 0; border-bottom:1px solid #f1f3f8; font-size:12px; }.appearance-coverage p { flex:1; color:#6b7891; }.appearance-coverage>span:last-child { flex-shrink:0; color:#99a3b4; font-size:10px; }.appearance-dot { flex-shrink:0; width:6px; height:6px; border-radius:50%; }.appearance-dot--ready { background:#5dbb9e; }.appearance-dot--pending { background:#e7b56d; }
.appearance-reason { margin-top:9px; color:#9a7849; font-size:12px; }.appearance-warning { margin-bottom:15px; padding:11px 14px; border-radius:8px; background:#fff4e8; color:#92602c; font-size:12px; }
.appearance-empty { display:flex; min-height:340px; flex-direction:column; align-items:center; justify-content:center; gap:12px; padding:28px; border:1px dashed #cdd8ed; border-radius:22px; background:linear-gradient(150deg,#f6f8ff,#fcfdff); text-align:center; color:#71809e; }.appearance-empty>span { color:#a8b7d5; font-size:54px; }.appearance-empty p { max-width:260px; font-size:12px; }
@media(max-width:850px) { .appearance-workspace__grid { grid-template-columns:1fr; gap:22px; }.appearance-workspace__heading { gap:12px; margin-bottom:18px; }.appearance-card { padding:18px; }.appearance-parts { grid-template-columns:1fr 1fr; } }
</style>
