// @vitest-environment happy-dom
import { beforeEach, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { api } from '@/api';
import { useGmPreferencesStore } from './index';

const fixtures = vi.hoisted(() => ({
  theme: { themeScheme: 'light', layout: { mode: 'vertical' }, tab: { visible: true }, setThemeScheme: vi.fn(), setThemeLayout: vi.fn() },
  app: { isMobile: false, siderCollapse: false, setSiderCollapse: vi.fn() }
}));
vi.mock('@/api', () => ({ api: vi.fn(), uncertainMessage: (error: Error) => error.message }));
vi.mock('@/store/modules/theme', () => ({ useThemeStore: () => fixtures.theme }));
vi.mock('@/store/modules/app', () => ({ useAppStore: () => fixtures.app }));
const saved = { pvf_sha256: 'a'.repeat(64), version: 3, payload: { theme: 'dark', layout: 'vertical', density: 'compact', sidebar_collapsed: true, show_job_art: false, tab_visible: true } };
beforeEach(() => { setActivePinia(createPinia()); vi.clearAllMocks(); fixtures.app.isMobile = false; });

it('loads PVF/version settings without writing or submitting operations', async () => {
  vi.mocked(api).mockResolvedValue(saved);
  const store = useGmPreferencesStore(); await store.load();
  expect(store.version).toBe(3); expect(store.showJobArt).toBe(false);
  expect(document.documentElement.dataset.gmDensity).toBe('compact');
  expect(api).toHaveBeenCalledExactlyOnceWith('/ui-preferences/layout/default');
  expect(fixtures.theme.setThemeScheme).toHaveBeenCalledWith('dark');
});

it('saves the loaded revision, preserves conflicts and never retries automatically', async () => {
  vi.mocked(api).mockResolvedValueOnce(saved).mockRejectedValueOnce(new Error('版本冲突'));
  const store = useGmPreferencesStore(); await store.load(); await store.save();
  expect(vi.mocked(api).mock.calls[1]).toMatchObject(['/ui-preferences/layout/default', 'PUT', { expected_version: 3, pvf_sha256: saved.pvf_sha256 }]);
  expect(store.version).toBe(3); expect(store.message).toBe('版本冲突'); expect(api).toHaveBeenCalledTimes(2);
});

it('discards an in-flight load after session reset', async () => {
  let resolve!: (value: typeof saved) => void;
  vi.mocked(api).mockReturnValue(new Promise(done => { resolve = done; }));
  const store = useGmPreferencesStore(); const loading = store.load(); store.reset(); resolve(saved); await loading;
  expect(store.loaded).toBe(false); expect(store.version).toBe(0); expect(store.showJobArt).toBe(true);
});

it('keeps mobile drawer navigation when reading a desktop layout', async () => {
  fixtures.app.isMobile = true; vi.mocked(api).mockResolvedValue(saved);
  await useGmPreferencesStore().load();
  expect(fixtures.theme.setThemeLayout).not.toHaveBeenCalled(); expect(fixtures.app.setSiderCollapse).not.toHaveBeenCalled();
});

