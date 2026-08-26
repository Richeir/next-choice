import { CollectionError, RetryableError } from './errors';
import { fetchText, withRetry } from './http';

describe('withRetry', () => {
  const baseOpts = { baseDelayMs: 100, jitter: () => 0.5 };

  test('retries retryable failures with exponential backoff and jitter', async () => {
    const delays: number[] = [];
    const sleep = async (ms: number) => {
      delays.push(ms);
    };
    let calls = 0;
    const result = await withRetry(
      async () => {
        calls++;
        if (calls < 3) throw new RetryableError('transient');
        return 'ok';
      },
      { ...baseOpts, sleep },
    );
    expect(result).toBe('ok');
    expect(calls).toBe(3);
    // baseDelay * 4^attempt * (1 + 0.5*jitter) = 100*1.25, 100*4*1.25
    expect(delays).toEqual([125, 500]);
  });

  test('passes through non-retryable errors immediately', async () => {
    let calls = 0;
    await expect(
      withRetry(
        async () => {
          calls++;
          throw new CollectionError('fatal');
        },
        { ...baseOpts, sleep: async () => undefined },
      ),
    ).rejects.toThrow(CollectionError);
    expect(calls).toBe(1);
  });

  test('rethrows last error after exhausting retries', async () => {
    let calls = 0;
    await expect(
      withRetry(
        async () => {
          calls++;
          throw new RetryableError('always');
        },
        { ...baseOpts, maxRetries: 2, sleep: async () => undefined },
      ),
    ).rejects.toThrow(RetryableError);
    // 首次 + 2 次重试
    expect(calls).toBe(3);
  });
});

describe('fetchText', () => {
  test('returns body text on ok', async () => {
    const fetchImpl = jest.fn(async () =>
      new Response('hello', { status: 200 }),
    );
    await expect(fetchText('http://x', { fetchImpl })).resolves.toBe('hello');
  });

  test('maps HTTP 5xx/429 to retryable, others to fatal', async () => {
    for (const status of [500, 503, 429]) {
      const fetchImpl = jest.fn(async () => new Response('', { status }));
      await expect(fetchText('http://x', { fetchImpl })).rejects.toThrow(
        RetryableError,
      );
    }
    const notFound = jest.fn(async () => new Response('', { status: 404 }));
    await expect(fetchText('http://x', { fetchImpl: notFound })).rejects.toThrow(
      CollectionError,
    );
  });

  test('maps network rejection to retryable', async () => {
    const fetchImpl = jest.fn(async () => {
      throw new TypeError('fetch failed');
    });
    await expect(fetchText('http://x', { fetchImpl })).rejects.toThrow(
      RetryableError,
    );
  });

  test('timeout aborts the request as retryable', async () => {
    const fetchImpl = (
      url: string,
      init?: RequestInit,
    ): Promise<Response> =>
      new Promise((_, reject) => {
        init?.signal?.addEventListener('abort', () =>
          reject(new Error('aborted')),
        );
      });
    await expect(
      fetchText('http://x', { fetchImpl, timeoutMs: 20 }),
    ).rejects.toThrow(RetryableError);
  });
});
