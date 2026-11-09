/** Explicitly register string-addressed local icons; other SVGs remain available to static imports. */
export const LOCAL_SPRITE_ICONS: readonly string[] = ['no-icon'];

export function getLocalIcons() {
  return [...LOCAL_SPRITE_ICONS];
}
