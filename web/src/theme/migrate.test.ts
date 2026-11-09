import { describe, expect, it } from 'vitest';
import { migrateLegacyGmPalette } from './migrate';
import { themeSettings } from './settings';

function legacy(): App.Theme.ThemeSetting {
  const settings = structuredClone(themeSettings);
  settings.themeColor = '#6265e8';
  settings.otherColor = { info: '#2080f0', success: '#52c41a', warning: '#faad14', error: '#f5222d' };
  settings.tokens.light.colors = { container: 'rgb(255, 255, 255)', layout: 'rgb(247, 250, 252)', inverted: 'rgb(0, 20, 40)', 'base-text': 'rgb(31, 31, 31)' };
  settings.tokens.dark = { colors: { container: 'rgb(28, 28, 28)', layout: 'rgb(18, 18, 18)', 'base-text': 'rgb(224, 224, 224)' } };
  return settings;
}

describe('legacy GM palette migration', () => {
  it('migrates the untouched palette without mutating saved navigation or accessibility preferences', () => {
    const saved = legacy();
    saved.themeScheme = 'auto';
    saved.layout.mode = 'horizontal';
    saved.sider.width = 256;
    saved.tab.visible = false;
    saved.colourWeakness = true;
    const snapshot = structuredClone(saved);
    const migrated = migrateLegacyGmPalette(saved);
    expect(saved).toEqual(snapshot);
    expect(migrated.themeColor).toBe(themeSettings.themeColor);
    expect(migrated.tokens.light.colors).toEqual(themeSettings.tokens.light.colors);
    expect(migrated.tokens.dark?.colors).toEqual(themeSettings.tokens.dark?.colors);
    expect(migrated.otherColor).toEqual(themeSettings.otherColor);
    expect(migrated).toMatchObject({ themeScheme: 'auto', layout: saved.layout, sider: saved.sider, tab: saved.tab, colourWeakness: true });
  });

  it.each(['primary', 'surface', 'status'] as const)('retains a custom %s palette unchanged', part => {
    const saved = legacy();
    if (part === 'primary') saved.themeColor = '#00849c';
    if (part === 'surface') saved.tokens.light.colors.layout = '#efefef';
    if (part === 'status') saved.otherColor.success = '#37724a';
    expect(migrateLegacyGmPalette(saved)).toBe(saved);
  });

  it('is idempotent for the current palette and a migrated palette', () => {
    expect(migrateLegacyGmPalette(themeSettings)).toBe(themeSettings);
    const migrated = migrateLegacyGmPalette(legacy());
    expect(migrateLegacyGmPalette(migrated)).toBe(migrated);
  });
});
