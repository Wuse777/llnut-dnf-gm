import type { GlobalThemeOverrides } from 'naive-ui';
import { defu } from 'defu';
import { addColorAlpha, getColorPalette, getPaletteColorByNumber, getRgb } from '@sa/color';
import { DARK_CLASS } from '@/constants/app';
import { toggleHtmlClass } from '@/utils/common';
import { localStg } from '@/utils/storage';
import { overrideThemeSettings, themeSettings } from '@/theme/settings';
import { themeVars } from '@/theme/vars';
import { applyStyleNonce } from '@/utils/style-nonce';
import { migrateLegacyGmPalette } from '@/theme/migrate';

/** Init theme settings */
export function initThemeSettings() {
  const isProd = import.meta.env.PROD;

  // if it is development mode, the theme settings will not be cached, by update `themeSettings` in `src/theme/settings.ts` to update theme settings
  if (!isProd) return themeSettings;

  // if it is production mode, the theme settings will be cached in localStorage
  // if want to update theme settings when publish new version, please update `overrideThemeSettings` in `src/theme/settings.ts`

  const localSettings = localStg.get('themeSettings');

  let settings = migrateLegacyGmPalette(defu(localSettings, themeSettings));

  const isOverride = localStg.get('overrideThemeFlag') === BUILD_TIME;

  if (!isOverride) {
    settings = defu(overrideThemeSettings, settings);

    localStg.set('overrideThemeFlag', BUILD_TIME);
  }

  return settings;
}

/**
 * create theme token css vars value by theme settings
 *
 * @param colors Theme colors
 * @param tokens Theme setting tokens
 * @param [recommended=false] Use recommended color. Default is `false`
 */
export function createThemeToken(
  colors: App.Theme.ThemeColor,
  tokens?: App.Theme.ThemeSetting['tokens'],
  recommended = false
) {
  const paletteColors = createThemePaletteColors(colors, recommended);

  const { light, dark } = tokens || themeSettings.tokens;

  const themeTokens: App.Theme.ThemeTokenCSSVars = {
    colors: {
      ...paletteColors,
      nprogress: paletteColors.primary,
      ...light.colors
    },
    boxShadow: {
      ...light.boxShadow
    }
  };

  const darkThemeTokens: App.Theme.ThemeTokenCSSVars = {
    colors: {
      ...themeTokens.colors,
      ...dark?.colors
    },
    boxShadow: {
      ...themeTokens.boxShadow,
      ...dark?.boxShadow
    }
  };

  return {
    themeTokens,
    darkThemeTokens
  };
}

/**
 * Create theme palette colors
 *
 * @param colors Theme colors
 * @param [recommended=false] Use recommended color. Default is `false`
 */
function createThemePaletteColors(colors: App.Theme.ThemeColor, recommended = false) {
  const colorKeys = Object.keys(colors) as App.Theme.ThemeColorKey[];
  const colorPaletteVar = {} as App.Theme.ThemePaletteColor;

  colorKeys.forEach(key => {
    const colorMap = getColorPalette(colors[key], recommended);

    colorPaletteVar[key] = colorMap.get(500)!;

    colorMap.forEach((hex, number) => {
      colorPaletteVar[`${key}-${number}`] = hex;
    });
  });

  return colorPaletteVar;
}

/**
 * Get css var by tokens
 *
 * @param tokens Theme base tokens
 */
function getCssVarByTokens(tokens: App.Theme.BaseToken) {
  const styles: string[] = [];

  function removeVarPrefix(value: string) {
    return value.replace('var(', '').replace(')', '');
  }

  function removeRgbPrefix(value: string) {
    return value.replace('rgb(', '').replace(')', '');
  }

  for (const [key, tokenValues] of Object.entries(themeVars)) {
    for (const [tokenKey, tokenValue] of Object.entries(tokenValues)) {
      let cssVarsKey = removeVarPrefix(tokenValue);
      let cssValue = tokens[key][tokenKey];

      if (key === 'colors') {
        cssVarsKey = removeRgbPrefix(cssVarsKey);
        const { r, g, b } = getRgb(cssValue);
        cssValue = `${r} ${g} ${b}`;
      }

      styles.push(`${cssVarsKey}: ${cssValue}`);
    }
  }

  // Full CSS colors for legacy GM forms; keep Soybean's RGB-channel variables separate.
  styles.push(
    `--gm-accent-color: ${tokens.colors.primary}`,
    `--gm-accent-hover: ${tokens.colors['primary-600']}`,
    `--gm-accent-active: ${tokens.colors['primary-700']}`,
    `--gm-accent-soft: ${addColorAlpha(tokens.colors.primary, 0.09)}`,
    `--gm-accent-border: ${addColorAlpha(tokens.colors.primary, 0.28)}`,
    `--gm-inverted-accent: ${tokens.colors['primary-300']}`,
    `--gm-container-color: ${tokens.colors.container}`,
    `--gm-layout-color: ${tokens.colors.layout}`,
    `--gm-base-text-color: ${tokens.colors['base-text']}`,
    `--gm-success-color: ${tokens.colors.success}`,
    `--gm-warning-color: ${tokens.colors.warning}`,
    `--gm-error-color: ${tokens.colors.error}`
  );

  const styleStr = styles.join(';');

  return styleStr;
}

/**
 * Add theme vars to global
 *
 * @param tokens
 */
export function addThemeVarsToGlobal(tokens: App.Theme.BaseToken, darkTokens: App.Theme.BaseToken) {
  const cssVarStr = getCssVarByTokens(tokens);
  const darkCssVarStr = getCssVarByTokens(darkTokens);

  const css = `
    :root {
      ${cssVarStr}
    }
  `;

  const darkCss = `
    html.${DARK_CLASS} {
      ${darkCssVarStr}
    }
  `;

  const styleId = 'theme-vars';

  const style = document.querySelector<HTMLStyleElement>(`#${styleId}`) || document.createElement('style');

  style.id = styleId;
  applyStyleNonce(style);

  style.textContent = css + darkCss;

  document.head.appendChild(style);
}

/**
 * Toggle css dark mode
 *
 * @param darkMode Is dark mode
 */
export function toggleCssDarkMode(darkMode = false) {
  const { add, remove } = toggleHtmlClass(DARK_CLASS);

  if (darkMode) {
    add();
  } else {
    remove();
  }
}

/**
 * Toggle auxiliary color modes
 *
 * @param grayscaleMode
 * @param colourWeakness
 */
export function toggleAuxiliaryColorModes(grayscaleMode = false, colourWeakness = false) {
  const htmlElement = document.documentElement;
  htmlElement.style.filter = [grayscaleMode ? 'grayscale(100%)' : '', colourWeakness ? 'invert(80%)' : '']
    .filter(Boolean)
    .join(' ');
}

type NaiveColorScene = '' | 'Suppl' | 'Hover' | 'Pressed' | 'Active';
type NaiveColorKey = `${App.Theme.ThemeColorKey}Color${NaiveColorScene}`;
type NaiveThemeColor = Partial<Record<NaiveColorKey, string>>;
interface NaiveColorAction {
  scene: NaiveColorScene;
  handler: (color: string) => string;
}

/**
 * Get naive theme colors
 *
 * @param colors Theme colors
 * @param [recommended=false] Use recommended color. Default is `false`
 */
function getNaiveThemeColors(colors: App.Theme.ThemeColor, recommended = false) {
  const colorActions: NaiveColorAction[] = [
    { scene: '', handler: color => color },
    { scene: 'Suppl', handler: color => color },
    { scene: 'Hover', handler: color => getPaletteColorByNumber(color, 500, recommended) },
    { scene: 'Pressed', handler: color => getPaletteColorByNumber(color, 700, recommended) },
    { scene: 'Active', handler: color => addColorAlpha(color, 0.1) }
  ];

  const themeColors: NaiveThemeColor = {};

  const colorEntries = Object.entries(colors) as [App.Theme.ThemeColorKey, string][];

  colorEntries.forEach(color => {
    colorActions.forEach(action => {
      const [colorType, colorValue] = color;
      const colorKey: NaiveColorKey = `${colorType}Color${action.scene}`;
      themeColors[colorKey] = action.handler(colorValue);
    });
  });

  return themeColors;
}

/**
 * Get naive theme
 *
 * @param colors Theme colors
 * @param settings Theme settings object
 * @param overrides Optional manual overrides from preset
 */
export function getNaiveTheme(
  colors: App.Theme.ThemeColor,
  settings: App.Theme.ThemeSetting,
  overrides?: GlobalThemeOverrides,
  darkMode = false
) {
  const { primary: colorLoading } = colors;
  const surfaces = darkMode ? { ...settings.tokens.light.colors, ...settings.tokens.dark?.colors } : settings.tokens.light.colors;
  const border = darkMode ? '#43483f' : '#e2e1d8';
  const muted = darkMode ? '#b3b7aa' : '#6b7167';
  const invertedAccent = settings.themeColor === '#92651f' ? '#d4ad66' : getPaletteColorByNumber(colors.primary, 300);

  const theme: GlobalThemeOverrides = {
    common: {
      ...getNaiveThemeColors(colors, settings.recommendColor),
      borderRadius: `${settings.themeRadius}px`,
      borderRadiusSmall: '5px',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif',
      fontSize: '14px',
      fontSizeSmall: '12px',
      heightMedium: '34px',
      heightSmall: '30px',
      textColorBase: surfaces['base-text'],
      textColor1: surfaces['base-text'],
      textColor2: surfaces['base-text'],
      textColor3: muted,
      placeholderColor: darkMode ? '#858d7e' : '#8b9085',
      borderColor: border,
      dividerColor: border,
      bodyColor: surfaces.layout,
      cardColor: surfaces.container,
      modalColor: surfaces.container,
      popoverColor: surfaces.container,
      inputColor: surfaces.container,
      tableColor: surfaces.container,
      invertedColor: settings.tokens.light.colors.inverted,
      buttonColor2: darkMode ? '#32382f' : '#f1f0e9',
      buttonColor2Hover: darkMode ? '#3c4338' : '#e9e8de',
      tableHeaderColor: darkMode ? '#2d332b' : '#f3f2ec',
      hoverColor: darkMode ? '#343a30' : '#f0efe7',
      tableColorHover: darkMode ? '#343a30' : '#f4f3ec',
      actionColor: darkMode ? '#2d332b' : '#f8f7f1'
    },
    LoadingBar: {
      colorLoading
    },
    Tag: {
      borderRadius: '5px'
    },
    Card: {
      borderRadius: '10px',
      paddingMedium: '20px',
      titleFontSizeMedium: '15px',
      titleFontWeight: '600'
    },
    Menu: {
      colorInverted: settings.tokens.light.colors.inverted,
      itemTextColorInverted: '#c9cec1',
      itemTextColorHoverInverted: '#f0f0e7',
      itemTextColorActiveInverted: invertedAccent,
      itemTextColorActiveHoverInverted: invertedAccent,
      itemIconColorActiveInverted: invertedAccent,
      itemIconColorActiveHoverInverted: invertedAccent,
      itemColorActiveInverted: addColorAlpha(invertedAccent, 0.12),
      itemColorActiveHoverInverted: addColorAlpha(invertedAccent, 0.17),
      itemColorHoverInverted: '#ffffff0c',
      borderRadius: '6px'
    }
  };

  // If there are overrides, merge them with priority
  // overrides has higher priority than auto-generated theme
  return overrides ? defu(overrides, theme) : theme;
}
