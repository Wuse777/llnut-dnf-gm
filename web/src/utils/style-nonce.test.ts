// @vitest-environment happy-dom
import { afterEach, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import { defineComponent, h } from 'vue';
import { addThemeVarsToGlobal, createThemeToken } from '@/store/modules/theme/shared';
import { themeSettings } from '@/theme/settings';
import { applyStyleNonce } from './style-nonce';

afterEach(() => {
  document.head.querySelectorAll('style,meta[property="csp-nonce"]').forEach(node => node.remove());
});

it('authorizes Naive component styles and the Soybean theme with the document nonce', async () => {
  const nonce = 'a'.repeat(43);
  const meta = document.createElement('meta');
  meta.setAttribute('property', 'csp-nonce');
  meta.nonce = nonce;
  document.head.appendChild(meta);
  // Production receives this meta in HTML before any JS modules execute.
  const { NButton, NCard, NConfigProvider, NInput } = await import('naive-ui');
  const tokens = createThemeToken({ primary: themeSettings.themeColor, ...themeSettings.otherColor });
  addThemeVarsToGlobal(tokens.themeTokens, tokens.darkThemeTokens);
  const wrapper = mount(defineComponent({ render: () => h(NConfigProvider, { inlineThemeDisabled: true }, {
    default: () => h(NCard, null, { default: () => [h(NInput), h(NButton, null, { default: () => '进入工作台' })] })
  }) }));
  const styles = [...document.head.querySelectorAll<HTMLStyleElement>('style')];
  expect(styles.length).toBeGreaterThan(3);
  expect(styles.filter(style => style.nonce !== nonce).map(style => style.getAttribute('cssr-id') || style.id)).toEqual([]);
  expect(styles.some(style => style.getAttribute('cssr-id')?.includes('input'))).toBe(true);
  expect(document.querySelector('#theme-vars')?.textContent).toContain('--primary-color');
  wrapper.unmount();
});

it('does not authorize styles when the server nonce is absent or still a build placeholder', () => {
  const style = document.createElement('style');
  applyStyleNonce(style);
  expect(style.hasAttribute('nonce')).toBe(false);
  const meta = document.createElement('meta');
  meta.setAttribute('property', 'csp-nonce');
  meta.nonce = '__DNFGM_STYLE_NONCE__';
  document.head.appendChild(meta);
  applyStyleNonce(style);
  expect(style.hasAttribute('nonce')).toBe(false);
});
