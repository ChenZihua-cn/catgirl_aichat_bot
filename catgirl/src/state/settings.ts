import { DEFAULT_SETTINGS, normalizeSettings } from '../config/defaults';
import type { Settings } from '../types';

const KEY = 'catgirl.settings.v1';

export function loadSettings(): Settings {
  const raw = localStorage.getItem(KEY);
  if (!raw) return { ...DEFAULT_SETTINGS };
  try {
    return normalizeSettings(JSON.parse(raw) as unknown);
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

export function saveSettings(settings: Settings): void {
  localStorage.setItem(KEY, JSON.stringify(settings));
}
