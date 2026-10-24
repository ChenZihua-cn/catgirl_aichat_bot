import type { RequestMessage, Sampling } from '../types';

export class LlamaServerError extends Error {
  status: number | undefined;

  constructor(message: string, status?: number) {
    super(message);
    this.name = 'LlamaServerError';
    this.status = status;
  }
}

/** 给面板和气泡共用的用户可读文案。 */
export function formatError(error: unknown): string {
  if (error instanceof LlamaServerError) {
    return error.status === 400 ? `请求被拒：${error.message}` : `llama-server：${error.message}`;
  }
  if (error instanceof TypeError) {
    return '连不上 llama-server，确认它已启动、地址和端口一致。';
  }
  return `出错了：${String(error)}`;
}

function endpoint(baseUrl: string, path: string): string {
  return `${baseUrl.replace(/\/+$/, '')}${path}`;
}

async function fail(res: Response): Promise<never> {
  let detail = `${res.status} ${res.statusText}`;
  try {
    const body = (await res.json()) as { error?: { message?: string } };
    if (body.error?.message) detail = body.error.message;
  } catch {
    // 错误体不是 JSON 时退回状态码
  }
  throw new LlamaServerError(detail, res.status);
}

export async function listModels(baseUrl: string, signal?: AbortSignal): Promise<string[]> {
  const res = await fetch(endpoint(baseUrl, '/v1/models'), { signal });
  if (!res.ok) return fail(res);
  const body = (await res.json()) as { data?: { id?: string }[] };
  return (body.data ?? []).map((m) => m.id ?? '').filter(Boolean);
}

export interface StreamArgs {
  baseUrl: string;
  model: string;
  messages: RequestMessage[];
  sampling: Sampling;
  signal: AbortSignal;
  onDelta: (text: string) => void;
}

/** llama-server 的 /v1/chat/completions 流式接口，返回完整文本。 */
export async function streamChat(args: StreamArgs): Promise<string> {
  const res = await fetch(endpoint(args.baseUrl, '/v1/chat/completions'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    signal: args.signal,
    body: JSON.stringify({
      model: args.model,
      messages: args.messages,
      stream: true,
      temperature: args.sampling.temperature,
      top_p: args.sampling.topP,
      repeat_penalty: args.sampling.repeatPenalty,
      max_tokens: args.sampling.maxTokens,
    }),
  });
  if (!res.ok) return fail(res);
  if (!res.body) throw new LlamaServerError('响应没有正文，无法流式读取');

  const reader = res.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  let full = '';
  let finished = false;

  const consumeLine = (line: string): void => {
    // 心跳与注释行以 ':' 开头
    if (!line.startsWith('data:')) return;
    const payload = line.slice(5).trim();
    if (payload === '[DONE]') {
      finished = true;
      return;
    }
    if (!payload) return;
    try {
      const chunk = JSON.parse(payload) as { choices?: { delta?: { content?: string } }[] };
      const text = chunk.choices?.[0]?.delta?.content;
      if (text) {
        full += text;
        args.onDelta(text);
      }
    } catch {
      // 单行解析失败只丢这一条增量，不中断整个回复
    }
  };

  while (!finished) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let newline = buffer.indexOf('\n');
    while (newline >= 0) {
      consumeLine(buffer.slice(0, newline).replace(/\r$/, ''));
      buffer = buffer.slice(newline + 1);
      if (finished) break;
      newline = buffer.indexOf('\n');
    }
  }

  await reader.cancel();
  return full;
}
