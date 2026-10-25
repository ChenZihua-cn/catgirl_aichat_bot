import type { Settings } from '../types';

export const DEFAULT_SETTINGS: Settings = {
  serverUrl: 'http://127.0.0.1:8080',
  model: '',
  usePersona: true,
  // 取 database/qwen_catgirl_ft/README.md 的推理建议：temp 0.7–0.9、repeat_penalty 1.05
  temperature: 0.8,
  topP: 0.9,
  repeatPenalty: 1.05,
  // llama-server 的 max_tokens 把推理模型的思考块一起计入预算：deepseek-r1 实测
  // 一条回复要 229 token（思考 284 字 + 正文 60 字）才自然停止，256 会把正文截没。
  maxTokens: 512,
  // 语料单条 2–6 轮、system 约 340 字，6 轮上下文仍在 2048 ctx 内
  historyTurns: 6,
  avatarOpacity: 100,
  fontSize: 14,
  animations: true,
  idleHideMinutes: 0,
};

export const RANGES = {
  temperature: { min: 0, max: 1.5, step: 0.05 },
  topP: { min: 0.1, max: 1, step: 0.05 },
  repeatPenalty: { min: 1, max: 1.4, step: 0.01 },
  maxTokens: { min: 64, max: 1024, step: 32 },
  historyTurns: { min: 0, max: 12, step: 1 },
  avatarOpacity: { min: 40, max: 100, step: 5 },
  fontSize: { min: 12, max: 20, step: 1 },
  idleHideMinutes: { min: 0, max: 30, step: 1 },
} as const;

export const WELCOME_LINES = [
  '喵…你回来啦。今天有没有好好吃饭。',
  '喂，别老盯着屏幕，眼睛不想要了？',
  '本喵才没有在等你，只是刚好路过。',
  '又加班？饭在微波炉里，自己去热。',
];

function clamp(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min;
  return Math.min(max, Math.max(min, value));
}

/** localStorage 是不可信输入：数值全部夹回合法区间，坏字段回落默认值。 */
export function normalizeSettings(raw: unknown): Settings {
  if (typeof raw !== 'object' || raw === null) return { ...DEFAULT_SETTINGS };
  const r = raw as Record<string, unknown>;
  const out: Settings = { ...DEFAULT_SETTINGS };

  if (typeof r.serverUrl === 'string' && /^https?:\/\//.test(r.serverUrl)) {
    out.serverUrl = r.serverUrl.replace(/\/+$/, '');
  }
  if (typeof r.model === 'string') out.model = r.model.trim();
  if (typeof r.usePersona === 'boolean') out.usePersona = r.usePersona;
  if (typeof r.animations === 'boolean') out.animations = r.animations;

  for (const key of Object.keys(RANGES) as (keyof typeof RANGES)[]) {
    const range = RANGES[key];
    const value = r[key];
    if (typeof value === 'number') {
      out[key] = clamp(value, range.min, range.max);
    }
  }
  return out;
}
