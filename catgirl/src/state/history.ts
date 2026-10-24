import type { ChatMessage } from '../types';

const KEY = 'catgirl.history.v1';
const MAX_MESSAGES = 200;

function isMessage(value: unknown): value is ChatMessage {
  if (typeof value !== 'object' || value === null) return false;
  const m = value as Record<string, unknown>;
  return (m.role === 'user' || m.role === 'assistant') && typeof m.content === 'string';
}

export function loadHistory(): ChatMessage[] {
  const raw = localStorage.getItem(KEY);
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isMessage).map((m) => ({ ...m, ts: Number(m.ts) || Date.now() }));
  } catch {
    return [];
  }
}

export function saveHistory(history: ChatMessage[]): void {
  localStorage.setItem(KEY, JSON.stringify(history.slice(-MAX_MESSAGES)));
}

export function clearHistory(): void {
  localStorage.removeItem(KEY);
}

/** 取最近 turns 轮（一问一答为一轮），并保证以 user 开头。 */
export function contextWindow(history: ChatMessage[], turns: number): ChatMessage[] {
  if (turns <= 0) return [];
  const window = history.slice(-turns * 2);
  return window.length > 0 && window[0]?.role === 'assistant' ? window.slice(1) : window;
}
