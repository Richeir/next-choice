import { makeMockFetch } from '../testing/mock-fetch';
import { listStocks } from './tencent-stock-list';
import { RetryableError } from '../errors';

const rankItem = (code: string, over: object = {}) => ({
  code,
  name: '贵州茅台',
  pe_ttm: '20.00',
  zsz: '16286.06',
  zxj: '1401.00',
  zdf: '-0.84',
  turnover: '283876',
  ...over,
});

const urlWithOffset = (offset: number) =>
  `offset=${offset}&`;

describe('listStocks', () => {
  test('maps tencent fields with unit conversion and code prefix strip', async () => {
    const fetchImpl = makeMockFetch([
      {
        match: (url) => url.includes(urlWithOffset(0)),
        body: {
          code: 0,
          msg: 'ok',
          data: { total: 3, rank_list: [rankItem('sh600519'), rankItem('sz000001'), rankItem('sh688808')] },
        },
      },
    ]);
    const items = await listStocks({ fetchImpl });
    expect(items).toHaveLength(3);
    expect(items[0]).toEqual({
      code: '600519',
      name: '贵州茅台',
      pe_ttm: 20,
      total_market_cap: 16286.06e8, // 亿 -> 元
      last_close: 1401,
      last_pct_chg: -0.84,
      last_amount: 2838760000, // 万 -> 元
    });
  });

  test('paginates by offset until total reached, dedupes keeping first', async () => {
    const page1 = Array.from({ length: 200 }, (_, i) =>
      rankItem(`sz${String(i + 1).padStart(6, '0')}`),
    );
    const page2 = [
      rankItem('sz000001'), // 与第 1 页重复，应被丢弃
      rankItem('sh688808'),
      rankItem('sh510050'),
      rankItem('sz159998'),
      rankItem('sh588660'),
    ];
    const fetchImpl = makeMockFetch([
      { match: (url) => url.includes(urlWithOffset(200)), body: { data: { total: 204, rank_list: page2 } } },
      { match: (url) => url.includes(urlWithOffset(0)), body: { data: { total: 204, rank_list: page1 } } },
    ]);
    const items = await listStocks({ fetchImpl });
    // 第 2 页的 sz000001 与第 1 页重复被丢弃：200 + 5 - 1
    expect(items).toHaveLength(204);
    expect(items.filter((i) => i.code === '000001')).toHaveLength(1);
  });

  test('empty rank_list before reaching total is retryable, not silent truncation', async () => {
    const fetchImpl = makeMockFetch([
      { match: () => true, body: { data: { total: 5550, rank_list: [] } } },
    ]);
    await expect(
      listStocks({
        fetchImpl,
        retry: { maxRetries: 1, baseDelayMs: 1, sleep: async () => undefined },
      }),
    ).rejects.toThrow(RetryableError);
  });

  test('dirty numeric fields map to null instead of NaN', async () => {
    const fetchImpl = makeMockFetch([
      {
        match: () => true,
        body: {
          data: {
            total: 1,
            rank_list: [rankItem('sh600000', { pe_ttm: '-', zxj: '', turnover: null })],
          },
        },
      },
    ]);
    const [item] = await listStocks({ fetchImpl });
    expect(item.pe_ttm).toBeNull();
    expect(item.last_close).toBeNull();
    expect(item.last_amount).toBeNull();
  });
});
