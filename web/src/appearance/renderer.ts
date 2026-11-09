import type { Appearance, AppearanceAction, Atlas, Clip } from './types';

export const CACHE_BUDGET = 64 * 1024 * 1024;
const shaPattern = /^[a-f0-9]{64}$/;

function integer(value: number, min: number, max: number): boolean {
  return Number.isInteger(value) && value >= min && value <= max;
}

/** Validate the same budget as the server before allocation or drawing. */
export function clipAssets(appearance: Appearance, action: AppearanceAction): { clip: Clip; pages: Atlas[] } {
  const clip = appearance.actions[action];
  if (!clip || !integer(clip.duration_ms, 1, 10000) || typeof clip.loop !== 'boolean' ||
    !Array.isArray(clip.frames) || !integer(clip.frames.length, 1, 120)) throw new Error('该动作暂不可用');
  const pages = new Map(appearance.atlases.map(page => [page.sha256, page]));
  const used = new Set<string>();
  let duration = 0;
  for (const frame of clip.frames) {
    if (!integer(frame.duration_ms, 1, 10000) || !Array.isArray(frame.draws) || frame.draws.length > 64) throw new Error('动作时间线超出预算');
    duration += frame.duration_ms;
    for (const draw of frame.draws) {
      const page = pages.get(draw.atlas);
      if (!page || !shaPattern.test(page.sha256) || !integer(page.width, 1, 2048) ||
        !integer(page.height, 1, 2048) || !integer(page.bytes, 33, 16 * 1024 * 1024) ||
        !new RegExp(`^/dnf-gm/api/v1/assets/[a-f0-9]{64}/${page.sha256}\\.atlas\\.png$`).test(page.url) ||
        !integer(draw.width, 1, 512) || !integer(draw.height, 1, 512) ||
        !integer(draw.sx, 0, page.width - draw.width) || !integer(draw.sy, 0, page.height - draw.height) ||
        !integer(draw.x, -256, 256 - draw.width) || !integer(draw.y, -448, 64 - draw.height) ||
        !integer(draw.z, -10000, 10000)) throw new Error('图集或角色锚点超出预算');
      used.add(page.sha256);
    }
  }
  if (duration !== clip.duration_ms) throw new Error('动作时长不一致');
  const selected = [...used].map(key => pages.get(key)!);
  if (selected.reduce((size, page) => size + page.width * page.height * 4, 0) > CACHE_BUDGET) throw new Error('当前动作超过64 MiB图集预算');
  return { clip, pages: selected };
}

export function frameAt(clip: Clip, elapsed: number): number {
  const time = clip.loop ? Math.max(0, elapsed) % clip.duration_ms : Math.min(Math.max(0, elapsed), clip.duration_ms - 1);
  let end = 0;
  for (let index = 0; index < clip.frames.length; index++) {
    end += clip.frames[index]!.duration_ms;
    if (time < end) return index;
  }
  return clip.frames.length - 1;
}

interface Entry { image: ImageBitmap; size: number; refs: number; used: number }
const cache = new Map<string, Entry>();
let memory = 0;

function evict(required: number): void {
  for (const [key, entry] of [...cache.entries()].sort((a, b) => a[1].used - b[1].used)) {
    if (memory + required <= CACHE_BUDGET) break;
    if (entry.refs) continue;
    entry.image.close(); memory -= entry.size; cache.delete(key);
  }
  if (memory + required > CACHE_BUDGET) throw new Error('图集缓存已满，请关闭其他角色预览');
}

/** Bound encoded allocation while streaming, even for a malformed response. */
export async function readAtlasBytes(response: Response, expected: number): Promise<ArrayBuffer> {
  if (!integer(expected, 33, 16 * 1024 * 1024) || !response.body) throw new Error('图集大小与清单不匹配');
  const declared = response.headers.get('content-length');
  if (declared !== null && Number(declared) !== expected) throw new Error('图集大小与清单不匹配');
  const buffer = new ArrayBuffer(expected);
  const output = new Uint8Array(buffer);
  const reader = response.body.getReader();
  let offset = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      if (offset + value.byteLength > expected) throw new Error('图集大小与清单不匹配');
      output.set(value, offset); offset += value.byteLength;
    }
    if (offset !== expected) throw new Error('图集大小与清单不匹配');
    return buffer;
  } catch (error) { await reader.cancel().catch(() => undefined); throw error; }
  finally { reader.releaseLock(); }
}

export async function acquireAtlases(pages: Atlas[], signal: AbortSignal): Promise<{ images: Map<string, ImageBitmap>; release: () => void }> {
  const keys: string[] = [];
  const images = new Map<string, ImageBitmap>();
  function release(): void {
    for (const key of keys.splice(0)) {
      const entry = cache.get(key);
      if (entry) { entry.refs = Math.max(0, entry.refs - 1); entry.used = performance.now(); }
    }
  }
  try {
    for (const page of pages) {
      signal.throwIfAborted();
      let entry = cache.get(page.sha256);
      if (!entry) {
        const required = page.width * page.height * 4;
        evict(required);
        const response = await fetch(page.url, { credentials: 'same-origin', signal });
        if (!response.ok || !response.headers.get('content-type')?.startsWith('image/png')) throw new Error('图集不可读取，请重新登录或检查素材包');
        const buffer = await readAtlasBytes(response, page.bytes);
        const hash = [...new Uint8Array(await crypto.subtle.digest('SHA-256', buffer))].map(v => v.toString(16).padStart(2, '0')).join('');
        if (hash !== page.sha256) throw new Error('图集摘要校验失败');
        signal.throwIfAborted();
        const bitmap = await createImageBitmap(new Blob([buffer], { type: 'image/png' }));
        if (signal.aborted || bitmap.width !== page.width || bitmap.height !== page.height) { bitmap.close(); signal.throwIfAborted(); throw new Error('图集尺寸与清单不匹配'); }
        // An overlapping view may have completed this same load while decoding.
        entry = cache.get(page.sha256);
        if (entry) bitmap.close();
        else {
          try { evict(required); }
          catch (error) { bitmap.close(); throw error; }
          entry = { image: bitmap, size: required, refs: 0, used: performance.now() }; cache.set(page.sha256, entry); memory += required;
        }
      }
      entry.refs++; entry.used = performance.now(); keys.push(page.sha256); images.set(page.sha256, entry.image);
    }
    return { images, release };
  } catch (error) { release(); throw error; }
}
