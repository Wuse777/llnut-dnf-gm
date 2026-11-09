import { themeSettings } from './settings';

/** Move the unchanged v0.6.5 palette forward; retain user colors, layout and accessibility preferences. */
export function migrateLegacyGmPalette(settings: App.Theme.ThemeSetting): App.Theme.ThemeSetting {
  const light = settings.tokens?.light?.colors;
  const dark = settings.tokens?.dark?.colors;
  const other = settings.otherColor;
  const unchanged = settings.themeColor?.toLowerCase() === '#6265e8'
    && light?.container === 'rgb(255, 255, 255)' && light.layout === 'rgb(247, 250, 252)'
    && light.inverted === 'rgb(0, 20, 40)' && light['base-text'] === 'rgb(31, 31, 31)'
    && dark?.container === 'rgb(28, 28, 28)' && dark.layout === 'rgb(18, 18, 18)'
    && dark['base-text'] === 'rgb(224, 224, 224)'
    && other?.info === '#2080f0' && other.success === '#52c41a'
    && other.warning === '#faad14' && other.error === '#f5222d';
  if (!unchanged) return settings;
  return {
    ...settings,
    themeColor: themeSettings.themeColor,
    otherColor: { ...themeSettings.otherColor },
    tokens: {
      ...settings.tokens,
      light: { ...settings.tokens.light, colors: { ...themeSettings.tokens.light.colors } },
      dark: { ...settings.tokens.dark, colors: { ...themeSettings.tokens.dark?.colors } }
    }
  };
}
