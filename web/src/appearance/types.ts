export type AppearanceAction = 'idle' | 'walk' | 'attack';
export interface AppearancePreset {
  job: number;
  grow_type?: number;
  sex?: number;
  slots: { slot: string; item_id: number }[];
  direction?: 'right' | 'mirror_left';
  animation?: AppearanceAction;
}
export interface Atlas {
  sha256: string;
  width: number;
  height: number;
  bytes: number;
  url: string;
}
export interface Draw {
  atlas: string;
  sx: number;
  sy: number;
  width: number;
  height: number;
  x: number;
  y: number;
  z: number;
}
export interface Clip {
  loop: boolean;
  duration_ms: number;
  frames: { duration_ms: number; draws: Draw[] }[];
}
export interface Appearance {
  version: 2;
  pvf_sha256?: string;
  state: string;
  source_kind: string;
  complete: boolean;
  client_verified: boolean;
  recipe_sha256?: string;
  recipe?: {
    job: number;
    grow_type: number;
    items: { slot: string; id: number; color1: number; color2: number }[];
  };
  actions: Partial<Record<AppearanceAction, Clip>>;
  atlases: Atlas[];
  reason_codes: string[];
  reasons: string[];
  coverage: { component: string; state: string; note: string; reason_code?: string }[];
  note: string;
}
