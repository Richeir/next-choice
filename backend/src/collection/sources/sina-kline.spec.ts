import { readFixture } from '../testing/mock-fetch';
import {
  applyQfqFactors,
  etfDaily,
  parseAmountJsonp,
  parseQfqFactors,
  shareResolver,
  stockDaily,
} from './sina-kline';
import { makeMockFetch } from '../testing/mock-fetch';
import { CollectionError, EmptyDataError } from '../errors';

const klcRoute = (symbol: string, body?: string) => ({
  match: (url: string) =>
    url.includes(`/realstock/company/${symbol}/hisdata_klc2/`),
  body: body ?? readFixture(`sina-kline-${symbol}.js`),
});

describe('parseAmountJsonp / shareResolver', () => {
  test('parses real jsonp shell and scales to shares with ffill semantics', () => {
    const entries = parseAmountJsonp(readFixture('sina-amount-sh688808.txt'));
    expect(entries).toEqual([{ date: '2026-04-24', wanShares: 1929.6144 }]);
    const resolve = shareResolver(
      entries.map((e) => ({ date: e.date, shares: e.wanShares * 1e4 })),
    );
    expect(resolve('2026-04-23')).toBeNull(); // 早于首条变更无数据
    expect(resolve('2026-04-24')).toBe(19296144);
    expect(resolve('2026-08-26')).toBe(19296144); // ffilled
  });

  test('malformed payload throws fatal error', () => {
    expect(() => parseAmountJsonp('no array here')).toThrow(CollectionError);
  });
});

describe('applyQfqFactors', () => {
  const bars = [
    { date: '2026-07-01', open: 100, high: 110, low: 98, close: 105, volume: 1, amount: 1, prevclose: null },
    { date: '2026-07-20', open: 10, high: 11, low: 9, close: 10.5, volume: 1, amount: 1, prevclose: null },
  ];

  test('divides prices by the effective factor (ex-div date inclusive)', () => {
    const out = applyQfqFactors(bars, [{ date: '2026-06-15', factor: 1.05 }]);
    expect(out.map((r) => r.close)).toEqual([100, 10]); // 105/1.05、10.5/1.05
  });

  test('bars before first factor are dropped (akshare dropna parity)', () => {
    const out = applyQfqFactors(bars, [{ date: '2026-07-10', factor: 2 }]);
    expect(out).toHaveLength(1);
    expect(out[0].date).toBe('2026-07-20');
    expect(out[0].close).toBe(5.25);
  });

  test('rounds adjusted prices to 2 decimals', () => {
    const out = applyQfqFactors([bars[0]], [{ date: '2026-01-01', factor: 3 }]);
    expect(out[0].close).toBe(Math.round((105 / 3) * 100) / 100); // 35
  });
});

describe('parseQfqFactors', () => {
  test('parses real qfq.js fixture sorted ascending, latest factor 1', () => {
    const factors = parseQfqFactors(readFixture('sina-qfq-sh600000.js'));
    expect(factors).toHaveLength(29);
    for (let i = 1; i < factors.length; i++) {
      expect(factors[i - 1].date < factors[i].date).toBe(true);
    }
    expect(factors[factors.length - 1]).toMatchObject({
      date: '2026-07-16',
      factor: 1,
    });
  });
});

describe('stockDaily', () => {
  test('fetches, decodes, computes turnover and filters window', async () => {
    const fetchImpl = makeMockFetch([
      klcRoute('sh688808'),
      {
        match: (url) => url.includes('getAmountBySymbol'),
        body: readFixture('sina-amount-sh688808.txt'),
      },
    ]);
    const rows = await stockDaily('688808', {
      start: '2026-04-24',
      end: '2026-08-26',
      fetchImpl,
    });
    expect(rows).toHaveLength(85);

    const first = rows[0];
    expect(first).toMatchObject({
      date: '2026-04-24',
      open: 736.92,
      high: 859.88,
      low: 688.99,
      close: 799,
      volume: 15178530,
      amount: 11413259860,
      preclose: null,
      pctChg: null,
    });
    // 换手率与 Python akshare 输出一致：volume / outstanding_share
    expect(first.turn).toBeCloseTo(0.7866094904764392, 10);

    const last = rows[rows.length - 1];
    expect(last.close).toBe(2259);
    expect(last.preclose).toBe(2209); // shift(1)：上一交易日收盘
    expect(last.pctChg).toBeCloseTo(((2259 - 2209) / 2209) * 100, 10);
    expect(last.turn).toBeCloseTo(0.03513453257811509, 10);

    // 股本请求确实发生（股票路径需要 turnover 分母）
    expect(fetchImpl.calls.some((u) => u.includes('getAmountBySymbol'))).toBe(true);
  });

  test('window filter excludes bars outside [start,end]', async () => {
    const fetchImpl = makeMockFetch([
      klcRoute('sh688808'),
      {
        match: (url) => url.includes('getAmountBySymbol'),
        body: readFixture('sina-amount-sh688808.txt'),
      },
    ]);
    const rows = await stockDaily('688808', {
      start: '2026-08-25',
      end: '2026-08-26',
      fetchImpl,
    });
    expect(rows.map((r) => r.date)).toEqual(['2026-08-25', '2026-08-26']);
  });

  test('unsupported adjust rejected without network', async () => {
    const fetchImpl = makeMockFetch([]);
    await expect(
      stockDaily('688808', {
        start: '2026-08-25',
        end: '2026-08-26',
        adjust: 'hfq' as never,
        fetchImpl,
      }),
    ).rejects.toThrow(/unsupported sina adjust/);
    expect(fetchImpl.calls).toHaveLength(0);
  });

  test('empty upstream payload is retried then surfaces EmptyDataError', async () => {
    let calls = 0;
    const fetchImpl = makeMockFetch([
      {
        match: () => true,
        get body() {
          calls++;
          return 'var KLC_K2_x="";';
        },
      },
    ]);
    await expect(
      stockDaily('688808', {
        start: '2026-01-01',
        end: '2026-01-02',
        fetchImpl,
        retry: { maxRetries: 1, baseDelayMs: 1, sleep: async () => undefined },
      }),
    ).rejects.toThrow(EmptyDataError);
    expect(calls).toBeGreaterThanOrEqual(2);
  });
});

describe('etfDaily', () => {
  test('uses decoded prevclose and pins oracle tail values', async () => {
    const fetchImpl = makeMockFetch([klcRoute('sh510050')]);
    const rows = await etfDaily('510050', {
      start: '2026-08-20',
      end: '2026-08-26',
      fetchImpl,
    });
    const last = rows[rows.length - 1];
    expect(last).toMatchObject({
      date: '2026-08-26',
      open: 2.982,
      high: 3.026,
      low: 2.979,
      close: 3.013,
      volume: 900314519,
      amount: 2710243189,
      preclose: null, // 解码尾部 prevclose 本就为空，如实保留
      pctChg: null,
    });
  });

  test('first historical bar keeps decoded preclose (0.887)', async () => {
    const fetchImpl = makeMockFetch([klcRoute('sh510050')]);
    const rows = await etfDaily('510050', {
      start: '2005-02-23',
      end: '2005-02-24',
      fetchImpl,
    });
    expect(rows[0].preclose).toBe(0.887);
    // 解密前收仅存在于早期个别 bar，缺失时如实为 null
    expect(rows[0].pctChg).toBeCloseTo(((0.876 - 0.887) / 0.887) * 100, 10);
  });
});
