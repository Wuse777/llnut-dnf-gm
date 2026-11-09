// @vitest-environment happy-dom
import { mount } from '@vue/test-utils';
import { afterEach, expect, it, vi } from 'vitest';
import { setupIconifyOffline } from './iconify';
import icons from 'virtual:dnfgm-offline-icons';
import SvgIcon from '../components/custom/svg-icon.vue';

afterEach(() => vi.unstubAllGlobals());

it('renders menu, theme and account controls without external icon requests', () => {
  const fetch = vi.fn(() => { throw new Error('UI icons must be offline'); });
  vi.stubGlobal('fetch', fetch);
  setupIconifyOffline();
  for (const name of ['ph:squares-four', 'ph:users', 'ph:gear-six', 'ph:user-circle', 'material-symbols:sunny', 'majesticons:color-swatch-line', 'ph:sidebar-simple']) {
    expect(icons[name], name).toBeDefined();
    const wrapper = mount(SvgIcon, { props: { icon: name } });
    expect(wrapper.find('svg').exists(), name).toBe(true);
    expect(wrapper.find('svg').element.childElementCount, name).toBeGreaterThan(0);
    wrapper.unmount();
  }
  expect(fetch).not.toHaveBeenCalled();
});

it('includes both collapsed menu and pin toggle states in a small registry', () => {
  for (const name of ['ph:caret-double-left-bold', 'ph:caret-double-right-bold', 'mdi:pin', 'mdi:pin-off', 'mdi:help-circle']) {
    expect(icons[name], name).toBeDefined();
  }
  expect(Object.keys(icons).length).toBeLessThan(100);
  expect(JSON.stringify(icons).length).toBeLessThan(100_000);
});

it('falls back for local icon names retained by old tabs instead of referencing removed symbols', () => {
  const wrapper = mount(SvgIcon, { props: { localIcon: 'expectation' } });
  expect(wrapper.find('use').element.getAttribute('xlink:href')).toBe('#icon-local-no-icon');
  wrapper.unmount();
});
