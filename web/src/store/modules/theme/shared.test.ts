// @vitest-environment happy-dom
import { afterEach, expect, it } from 'vitest';
import { themeSettings } from '@/theme/settings';
import { addThemeVarsToGlobal, createThemeToken, getNaiveTheme } from './shared';

afterEach(() => document.querySelector('#theme-vars')?.remove());

it('provides channel variables for the shell and complete color aliases for GM controls', () => {
  const colors = { primary: '#00849c', ...themeSettings.otherColor };
  const tokens = createThemeToken(colors);
  addThemeVarsToGlobal(tokens.themeTokens, tokens.darkThemeTokens);
  const css = document.querySelector('#theme-vars')!.textContent!;
  expect(css).toContain('--primary-color: 0 132 156');
  expect(css).toContain('--gm-accent-color: #00849c');
  expect(css).toContain(`--gm-container-color: ${themeSettings.tokens.light.colors.container}`);
  expect(css).toContain(`--gm-container-color: ${themeSettings.tokens.dark?.colors?.container}`);
});

it('matches Naive surfaces to the active light and dark GM palette', () => {
  const colors = { primary: themeSettings.themeColor, ...themeSettings.otherColor };
  const light = getNaiveTheme(colors, themeSettings);
  const dark = getNaiveTheme(colors, themeSettings, undefined, true);
  expect(light.common?.cardColor).toBe(themeSettings.tokens.light.colors.container);
  expect(dark.common?.cardColor).toBe(themeSettings.tokens.dark?.colors?.container);
  expect(light.common?.primaryColor).toBe(themeSettings.themeColor);
  expect(light.Menu?.itemTextColorActiveInverted).toBe('#d4ad66');
});

it('honors explicitly supplied component theme overrides', () => {
  const colors = { primary: '#00849c', ...themeSettings.otherColor };
  const theme = getNaiveTheme(colors, themeSettings, { common: { primaryColor: '#660099' }, Card: { borderRadius: '2px' } });
  expect(theme.common?.primaryColor).toBe('#660099');
  expect(theme.Card?.borderRadius).toBe('2px');
  expect(theme.common?.cardColor).toBe(themeSettings.tokens.light.colors.container);
});
