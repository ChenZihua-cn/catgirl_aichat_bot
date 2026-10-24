import { PERSONA_PROMPT } from '../config/persona';
import { WELCOME_LINES } from '../config/defaults';
import { contextWindow, loadHistory, saveHistory } from '../state/history';
import { formatError, streamChat } from '../services/llamaServer';
import type { ChatMessage, RequestMessage, Settings } from '../types';
import type { PetWindow } from './pet';

export interface ChatDeps {
  pet: PetWindow;
  getSettings: () => Settings;
  /** 解析实际要请求的模型别名（settings 里可以留空，由调用方回落服务端首个） */
  resolveModel: () => Promise<string>;
  onActivity: () => void;
}

const MAX_INPUT_HEIGHT = 84;

export class Chat {
  private history: ChatMessage[] = loadHistory();
  private busy = false;
  private inflight: AbortController | null = null;

  private readonly log = mustGet<HTMLDivElement>('log');
  private readonly input = mustGet<HTMLTextAreaElement>('input');
  private readonly sendButton = mustGet<HTMLButtonElement>('send');
  private readonly hint = mustGet<HTMLDivElement>('hint');
  private readonly typing = mustGet<HTMLDivElement>('typing');

  constructor(private readonly deps: ChatDeps) {}

  mount(): void {
    this.renderAll();

    this.sendButton.addEventListener('click', () => {
      void this.send();
    });

    this.input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        void this.send();
      }
      if (event.key === 'Escape') this.cancel();
    });

    this.input.addEventListener('input', () => this.autoGrow());
  }

  focusInput(): void {
    this.input.focus();
  }

  /** 无历史时补一句开场白，不走推理。 */
  greet(): void {
    if (this.history.length > 0) return;
    const line = WELCOME_LINES[Math.floor(Math.random() * WELCOME_LINES.length)];
    if (line) this.say({ role: 'assistant', content: line, ts: Date.now() });
  }

  cancel(): void {
    this.inflight?.abort();
  }

  clear(): void {
    this.cancel();
    this.history = [];
    saveHistory(this.history);
    this.log.replaceChildren();
  }

  private async send(): Promise<void> {
    const text = this.input.value.trim();
    if (!text || this.busy) return;

    const settings = this.deps.getSettings();
    this.input.value = '';
    this.autoGrow();
    this.setHint(null);
    this.say({ role: 'user', content: text, ts: Date.now() });
    this.deps.onActivity();

    const messages: RequestMessage[] = settings.usePersona
      ? [{ role: 'system', content: PERSONA_PROMPT }, ...contextWindow(this.history, settings.historyTurns)]
      : contextWindow(this.history, settings.historyTurns);

    const bubble = this.openAssistantBubble();
    this.busy = true;
    this.inflight = new AbortController();
    this.setBusyUi(true);
    this.deps.pet.setMood('thinking');

    try {
      const model = await this.deps.resolveModel();
      const reply = await streamChat({
        baseUrl: settings.serverUrl,
        model,
        messages,
        sampling: {
          temperature: settings.temperature,
          topP: settings.topP,
          repeatPenalty: settings.repeatPenalty,
          maxTokens: settings.maxTokens,
        },
        signal: this.inflight.signal,
        onDelta: (delta) => bubble.appendText(delta),
      });

      const content = reply.trim();
      if (content) {
        this.record({ role: 'assistant', content, ts: Date.now() });
        bubble.finalize(content);
        this.deps.pet.setMood('talking');
      } else {
        bubble.remove();
        this.setHint('她没接上话，检查 llama-server 的模型别名和上下文长度。');
        this.deps.pet.setMood('idle');
      }
    } catch (error) {
      bubble.remove();
      if (error instanceof DOMException && error.name === 'AbortError') {
        this.setHint('已打断。');
      } else {
        this.setHint(formatError(error));
      }
      this.deps.pet.setMood('idle');
    } finally {
      this.inflight = null;
      this.busy = false;
      this.setBusyUi(false);
    }
  }

  /** 只写历史与存档，不碰 DOM。 */
  private record(message: ChatMessage): void {
    this.history = [...this.history.slice(-199), message];
    saveHistory(this.history);
  }

  /** 记一条并立刻画出来。 */
  private say(message: ChatMessage): void {
    this.record(message);
    this.renderMessage(message);
    this.scrollToEnd();
  }

  private renderAll(): void {
    this.log.replaceChildren(...this.history.map((m) => createBubble(m)));
    this.scrollToEnd();
  }

  private renderMessage(message: ChatMessage): void {
    this.log.append(createBubble(message));
  }

  private openAssistantBubble(): StreamingBubble {
    const element = document.createElement('div');
    element.className = 'msg msg--assistant';
    this.log.append(element);
    this.scrollToEnd();
    return {
      appendText: (delta: string) => {
        element.append(delta);
        this.scrollToEnd();
      },
      finalize: (content: string) => {
        element.textContent = content;
        this.scrollToEnd();
      },
      remove: () => element.remove(),
    };
  }

  private setBusyUi(busy: boolean): void {
    this.sendButton.disabled = busy;
    this.sendButton.textContent = busy ? '停止' : '发送';
    this.typing.hidden = !busy;
  }

  private setHint(text: string | null): void {
    this.hint.textContent = text ?? '';
    this.hint.hidden = text === null;
  }

  private autoGrow(): void {
    this.input.style.height = 'auto';
    this.input.style.height = `${Math.min(this.input.scrollHeight, MAX_INPUT_HEIGHT)}px`;
  }

  private scrollToEnd(): void {
    this.log.scrollTop = this.log.scrollHeight;
  }
}

interface StreamingBubble {
  appendText: (delta: string) => void;
  finalize: (content: string) => void;
  remove: () => void;
}

function createBubble(message: ChatMessage): HTMLElement {
  const element = document.createElement('div');
  element.className = `msg msg--${message.role}`;
  element.textContent = message.content;
  return element;
}

function mustGet<T extends HTMLElement>(id: string): T {
  const element = document.getElementById(id);
  if (!element) throw new Error(`缺少 #${id} 节点`);
  return element as T;
}
