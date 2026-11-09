import { describe, expect, it } from 'vitest';
import { clipAssets, frameAt, readAtlasBytes } from './renderer';
import type { Appearance, Clip } from './types';

const clip: Clip = { loop: true, duration_ms: 200, frames: [{ duration_ms: 70, draws: [] }, { duration_ms: 130, draws: [] }] };
describe('appearance timeline', () => {
  it('keeps source durations, loop boundaries and one-shot last frame', () => {
    expect(frameAt(clip, 69)).toBe(0); expect(frameAt(clip, 70)).toBe(1); expect(frameAt(clip, 200)).toBe(0);
    expect(frameAt({ ...clip, loop: false }, 300)).toBe(1);
  });
  it('refuses drawing outside registered atlas or fixed character canvas', () => {
    const sha = 'a'.repeat(64);
    const draw = { atlas: sha, sx: 0, sy: 0, width: 20, height: 20, x: 0, y: -20, z: 1000 };
    const appearance = { actions: { idle: { loop: true, duration_ms: 100, frames: [{ duration_ms: 100, draws: [draw] }] } },
      atlases: [{ sha256: sha, width: 1024, height: 512, bytes: 100, url: `/dnf-gm/api/v1/assets/${'b'.repeat(64)}/${sha}.atlas.png` }] } as Appearance;
    expect(clipAssets(appearance, 'idle').pages).toHaveLength(1);
    draw.x = 255; expect(() => clipAssets(appearance, 'idle')).toThrow(); draw.x = 0;
    appearance.atlases[0]!.url = 'https://example.com/foreign.png'; expect(() => clipAssets(appearance, 'idle')).toThrow();
  });
  it('stops oversized or truncated encoded streams before image decoding', async () => {
    expect((await readAtlasBytes(new Response(new Uint8Array(40)), 40)).byteLength).toBe(40);
    await expect(readAtlasBytes(new Response(new Uint8Array(41)), 40)).rejects.toThrow();
    await expect(readAtlasBytes(new Response(new Uint8Array(39)), 40)).rejects.toThrow();
  });
});
