import { CollectionError, RetryableError } from './errors';

/** 可注入的 fetch 实现（测试用 mock 替换，生产用全局 fetch）。 */
export type FetchLike = (url: string, init?: RequestInit) => Promise<Response>;

export const defaultFetchImpl: FetchLike = (url, init) =>
  globalThis.fetch(url, init);

export interface RetryOptions {
  /** 最大重试次数（不含首次调用），默认 3。 */
  maxRetries?: number;
  /** 首次退避基数（毫秒），默认 1000。 */
  baseDelayMs?: number;
  /** 睡眠函数（测试注入假时钟）。 */
  sleep?: (ms: number) => Promise<void>;
  /** [0,1) 随机数来源（测试注入定值），避免全市场循环齐步重试。 */
  jitter?: () => number;
}

const defaultSleep = (ms: number) =>
  new Promise<void>((resolve) => setTimeout(resolve, ms));

/**
 * 对 fn 做指数退避重试；只捕获 {@link RetryableError}，其他异常直接抛出。
 * 退避时长 baseDelayMs * 4^attempt * (1 + 0.5*jitter())，
 * 与 Python 侧 fetch_with_retry 的公式保持一致。
 */
export async function withRetry<T>(
  fn: () => Promise<T>,
  opts: RetryOptions = {},
): Promise<T> {
  const maxRetries = opts.maxRetries ?? 3;
  const baseDelayMs = opts.baseDelayMs ?? 1000;
  const sleep = opts.sleep ?? defaultSleep;
  const jitter = opts.jitter ?? Math.random;
  let last: unknown;
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      return await fn();
    } catch (e) {
      if (!(e instanceof RetryableError)) throw e;
      last = e;
      if (attempt >= maxRetries) break;
      const delay = baseDelayMs * 4 ** attempt * (1 + 0.5 * jitter());
      await sleep(delay);
    }
  }
  throw last;
}

export interface FetchTextOptions {
  fetchImpl?: FetchLike;
  headers?: Record<string, string>;
  /** 单次请求超时（毫秒），默认 15000。 */
  timeoutMs?: number;
}

/** 单次 HTTP GET 文本。5xx/429 与网络异常视为可重试，其余非 2xx 为致命。 */
export async function fetchText(
  url: string,
  opts: FetchTextOptions = {},
): Promise<string> {
  const fetchImpl = opts.fetchImpl ?? defaultFetchImpl;
  const controller = new AbortController();
  const timer = setTimeout(
    () => controller.abort(),
    opts.timeoutMs ?? 15000,
  );
  try {
    const res = await fetchImpl(url, {
      headers: opts.headers,
      signal: controller.signal,
    });
    if (res.status >= 500 || res.status === 429) {
      throw new RetryableError(`HTTP ${res.status} from ${url}`);
    }
    if (!res.ok) {
      throw new CollectionError(`HTTP ${res.status} from ${url}`);
    }
    return await res.text();
  } catch (e) {
    if (e instanceof CollectionError) throw e;
    // fetch 网络层异常（TypeError 等）与超时中止都是瞬时故障。
    throw new RetryableError(
      `fetch failed: ${e instanceof Error ? e.message : String(e)}`,
    );
  } finally {
    clearTimeout(timer);
  }
}
