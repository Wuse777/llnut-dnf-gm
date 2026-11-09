// @vitest-environment happy-dom
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { defineComponent, h, onMounted, reactive } from 'vue';
import { mount, flushPromises } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import { themeSettings } from '@/theme/settings';
import GlobalContent from './index.vue';

const stores = vi.hoisted(() => ({ app: null as any, theme: null as any, tab: null as any }));
vi.mock('@sa/materials', () => ({ LAYOUT_SCROLL_EL_ID: 'gm-test-scroll' }));
vi.mock('@/store/modules/app', () => ({ useAppStore: () => stores.app }));
vi.mock('@/store/modules/theme', () => ({ useThemeStore: () => stores.theme }));
vi.mock('@/store/modules/tab', () => ({ useTabStore: () => stores.tab }));

let wrapper: ReturnType<typeof mount> | undefined;
const originalAnimate = Object.getOwnPropertyDescriptor(Element.prototype, 'animate');
const animations: { finished: Promise<void>; cancel: ReturnType<typeof vi.fn> }[] = [];
const animate = vi.fn(() => {
  let reject: () => void = () => {};
  const animation = {
    finished: new Promise<void>((_, rejectFinished) => { reject = () => rejectFinished(new Error('cancelled')); }),
    cancel: vi.fn(() => reject())
  };
  animations.push(animation);
  return animation;
});

function motion(reduce: boolean) {
  vi.stubGlobal('matchMedia', vi.fn((query: string) => ({
    matches: reduce && query.includes('prefers-reduced-motion'), media: query,
    addEventListener: vi.fn(), removeEventListener: vi.fn()
  })));
}

beforeEach(() => {
  stores.app = reactive({ reloadFlag: true, setContentXScrollable: vi.fn() });
  stores.theme = reactive({ page: { ...themeSettings.page } });
  stores.tab = { getTabIdByRoute: (route: { fullPath: string }) => route.fullPath };
  animate.mockClear();
  animations.length = 0;
  Object.defineProperty(Element.prototype, 'animate', { configurable: true, value: animate });
  motion(false);
});

afterEach(async () => {
  wrapper?.unmount();
  wrapper = undefined;
  await flushPromises();
  vi.unstubAllGlobals();
  if (originalAnimate) Object.defineProperty(Element.prototype, 'animate', originalAnimate);
  else Reflect.deleteProperty(Element.prototype, 'animate');
  document.body.innerHTML = '';
});

async function setup() {
  const mounts: string[] = [], formsAtMount: number[] = [];
  function page(label: string) {
    return defineComponent({
      setup() {
        mounts.push(label);
        onMounted(() => formsAtMount.push(document.querySelectorAll('#gm-write-form').length));
        return () => h('form', { id: 'gm-write-form', 'data-player': label }, [h('input', { value: '' })]);
      }
    });
  }
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/one', component: page('one') }, { path: '/two', component: page('two') }
  ] });
  await router.push('/one');
  await router.isReady();
  wrapper = mount(GlobalContent, { attachTo: document.body, global: { plugins: [router], stubs: { transition: false } } });
  await flushPromises();
  return { router, mounts, formsAtMount };
}

it('defaults to immediate navigation and remounts player forms without KeepAlive', async () => {
  expect(themeSettings.page.animate).toBe(false);
  const { router, mounts, formsAtMount } = await setup();
  await wrapper!.find('input').setValue('first player value');
  await router.push('/two');
  await flushPromises();
  expect(wrapper!.find('form').attributes('data-player')).toBe('two');
  await router.push('/one');
  await flushPromises();
  expect(mounts).toEqual(['one', 'two', 'one']);
  expect((wrapper!.find('input').element as HTMLInputElement).value).toBe('');
  expect(formsAtMount).toEqual([1, 1, 1]);
  expect(animate).not.toHaveBeenCalled();
});

it('supports a saved slide preference with a 100ms entry fade and synchronous old-form removal', async () => {
  stores.theme.page = { animate: true, animateMode: 'fade-slide' };
  const { router, formsAtMount } = await setup();
  await router.push('/two');
  await flushPromises();
  expect(animate).toHaveBeenCalledWith([{ opacity: 0 }, { opacity: 1 }], { duration: 100, easing: 'ease-out' });
  // The entry animation remains unfinished when the next navigation is requested.
  await router.push('/one');
  await flushPromises();
  expect(animations[0].cancel).toHaveBeenCalledOnce();
  expect(wrapper!.find('form').attributes('data-player')).toBe('one');
  expect(document.querySelectorAll('#gm-write-form')).toHaveLength(1);
  expect(formsAtMount).toEqual([1, 1, 1]);
});

it('honors a saved none mode', async () => {
  stores.theme.page = { animate: true, animateMode: 'none' };
  const { router } = await setup();
  await router.push('/two');
  await flushPromises();
  expect(wrapper!.find('form').attributes('data-player')).toBe('two');
  expect(animate).not.toHaveBeenCalled();
});

it('disables page motion when the operating system requests reduced motion', async () => {
  motion(true);
  stores.theme.page = { animate: true, animateMode: 'zoom-fade' };
  const { router } = await setup();
  await router.push('/two');
  await flushPromises();
  expect(wrapper!.find('form').attributes('data-player')).toBe('two');
  expect(animate).not.toHaveBeenCalled();
});

it('keeps navigation immediate if the animation API fails', async () => {
  stores.theme.page = { animate: true, animateMode: 'fade' };
  animate.mockImplementationOnce(() => { throw new Error('unsupported animation'); });
  const { router, formsAtMount } = await setup();
  await router.push('/two');
  await flushPromises();
  expect(wrapper!.find('form').attributes('data-player')).toBe('two');
  expect(formsAtMount).toEqual([1, 1]);
});
