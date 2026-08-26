import { makeMockFetch } from '../testing/mock-fetch';
import { etfCategoryMap } from './ths-etf-category';
import { EmptyDataError } from '../errors';

describe('etfCategoryMap', () => {
  const fastRetry = { maxRetries: 0, baseDelayMs: 1, sleep: async () => undefined };

  test('parses jsonp payload into code -> typename map', async () => {
    const fetchImpl = makeMockFetch([
      {
        match: (url) => url.includes('fund.10jqka.com.cn') && url.includes('ETF_rate_desc'),
        body:
          '(jsonp({"data":{"info":{"count":2},"data":' +
          JSON.stringify({
            '510300': { typename: '指数型' },
            '159998': { typename: '行业型' },
          }) +
          '}}))',
      },
    ]);
    const map = await etfCategoryMap({ fetchImpl, retry: fastRetry });
    expect(map).toEqual({ '510300': '指数型', '159998': '行业型' });
  });

  test('degraded PHP-serialized response is retryable EmptyDataError', async () => {
    // 真实降级响应存档（同花顺对代理出口 IP 风控时的"能解析的空包"）
    const degraded =
      'a:2:{s:4:"data";a:2:{s:4:"info";a:6:{s:5:"count";i:0;' +
      's:4:"star";s:10:"2026-08-26";}s:4:"data";b:0;}' +
      's:5:"error";a:2:{s:2:"id";i:0;s:3:"msg";s:9:"is access";}}';
    let calls = 0;
    const fetchImpl = makeMockFetch([
      {
        match: () => true,
        get body() {
          calls++;
          return degraded;
        },
      },
    ]);
    await expect(
      etfCategoryMap({
        fetchImpl,
        retry: { maxRetries: 1, baseDelayMs: 1, sleep: async () => undefined },
      }),
    ).rejects.toThrow(EmptyDataError);
    expect(calls).toBe(2); // 重试了一次
  });

  test('empty inner dataset throws EmptyDataError', async () => {
    const fetchImpl = makeMockFetch([
      { match: () => true, body: '(jsonp({"data":{"info":{"count":0},"data":{}}}))' },
    ]);
    await expect(etfCategoryMap({ fetchImpl, retry: fastRetry })).rejects.toThrow(
      EmptyDataError,
    );
  });
});
