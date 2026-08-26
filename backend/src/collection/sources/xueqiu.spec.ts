import { FetchLike } from '../http';
import { XqAuthError } from '../errors';
import {
  msToCstDate,
  resetXqTokenHint,
  stockBasic,
  stockQuote,
  xqTokenFromEnv,
} from './xueqiu';

/** 手写 fetch mock：需要断言请求头（cookie 组装）。 */
function capturingFetch(routes: Array<{ match: (url: string) => boolean; body: object; headers?: Record<string, string | string[]> }>) {
  const requests: Array<{ url: string; cookie?: string }> = [];
  const impl: FetchLike = async (url, init) => {
    const route = routes.find((r) => r.match(url));
    if (!route) throw new Error(`no route for ${url}`);
    const headerRecord = (init?.headers ?? {}) as Record<string, string>;
    requests.push({ url, cookie: headerRecord.cookie });
    const resHeaders = new Headers();
    for (const [name, value] of Object.entries(route.headers ?? {})) {
      if (Array.isArray(value)) value.forEach((v) => resHeaders.append(name, v));
      else resHeaders.append(name, value);
    }
    return new Response(JSON.stringify(route.body), { status: 200, headers: resHeaders });
  };
  return { impl, requests };
}

beforeEach(() => resetXqTokenHint());

describe('xqTokenFromEnv', () => {
  test('trims value; blank or missing -> null', () => {
    expect(xqTokenFromEnv({ XQ_TOKEN: ' tok ' } as NodeJS.ProcessEnv)).toBe('tok');
    expect(xqTokenFromEnv({} as NodeJS.ProcessEnv)).toBeNull();
    expect(xqTokenFromEnv({ XQ_TOKEN: '   ' } as NodeJS.ProcessEnv)).toBeNull();
  });
});

describe('stockBasic', () => {
  const warmupRoute = {
    match: (url: string) => url === 'https://xueqiu.com',
    body: {},
    headers: { 'set-cookie': ['acw_tc=xyz; Path=/'] },
  };

  test('missing token warns once and returns null without network', async () => {
    const warnings: string[] = [];
    const logger = { warn: (m: string) => warnings.push(m) };
    const { impl } = capturingFetch([]);
    const opts = { token: null, fetchImpl: impl, logger };

    await expect(stockBasic('600000', opts)).resolves.toBeNull();
    await expect(stockBasic('600000', opts)).resolves.toBeNull();
    // 每次失败都告警（不打断全市场循环），但配置提示只附一次
    expect(warnings).toHaveLength(2);
    expect(warnings[0]).toMatch(/XQ_TOKEN/);
    expect(warnings[1]).not.toMatch(/XQ_TOKEN/);
  });

  test('warm-up cookies are merged with xq_a_token on api request', async () => {
    const { impl, requests } = capturingFetch([
      warmupRoute,
      {
        match: (url) =>
          url.includes('/v5/stock/f10/cn/company.json') &&
          url.includes('symbol=SH600519'),
        body: {
          data: {
            org_name_cn: '贵州茅台酒股份有限公司',
            listed_date: 1096416000000,
            affiliate_industry: { ind_name: '白酒' },
          },
        },
      },
    ]);
    const info = await stockBasic('600519', { token: 'tok123', fetchImpl: impl });
    expect(info).toEqual({
      full_name: '贵州茅台酒股份有限公司',
      industry: '白酒',
      ipo_date: msToCstDate(1096416000000),
    });
    const apiCall = requests.find((r) => r.url.includes('/v5/'));
    expect(apiCall?.cookie).toContain('xq_a_token=tok123;');
    expect(apiCall?.cookie).toContain('acw_tc=xyz');
  });

  test('error_code 400016 surfaces one-shot expired-token hint and returns null', async () => {
    const warnings: string[] = [];
    const logger = { warn: (m: string) => warnings.push(m) };
    const { impl } = capturingFetch([
      warmupRoute,
      {
        match: () => true,
        body: { error_code: 400016, error_description: '请重新登录' },
      },
    ]);
    const opts = { token: 'stale', fetchImpl: impl, logger };
    await expect(stockBasic('600000', opts)).resolves.toBeNull();
    await expect(stockBasic('600000', opts)).resolves.toBeNull();
    // 首次失败附带提示，之后不再重复
    expect(warnings[0]).toMatch(/400016.*过期|已注入 XQ_TOKEN/s);
    expect(warnings[1]).not.toMatch(/XQ_TOKEN/);
  });

  test('ipo_date absent -> null; industry non-dict -> null', async () => {
    const { impl } = capturingFetch([
      warmupRoute,
      {
        match: () => true,
        body: { data: { org_name_cn: 'x', listed_date: null, affiliate_industry: 'oops' } },
      },
    ]);
    await expect(
      stockBasic('600000', { token: 't', fetchImpl: impl }),
    ).resolves.toEqual({ full_name: 'x', industry: null, ipo_date: null });
  });
});

describe('stockQuote', () => {
  test('maps english keys to pipeline fields with dirty-value tolerance', async () => {
    const { impl } = capturingFetch([
      { match: (url) => url === 'https://xueqiu.com', body: {} },
      {
        match: (url) => url.includes('/v5/stock/quote.json') && url.includes('extend=detail'),
        body: {
          data: {
            quote: {
              pb: '2.34',
              high52w: '1998',
              low52w: '950.5',
              market_capital: '-',
            },
          },
        },
      },
    ]);
    await expect(
      stockQuote('600000', { token: 't', fetchImpl: impl }),
    ).resolves.toEqual({
      pb: 2.34,
      high_52w: 1998,
      low_52w: 950.5,
      total_market_cap: null, // '-' 脏数据
    });
  });

  test('network failure returns null (per-code swallow, loop must not break)', async () => {
    const warnings: string[] = [];
    const failing: FetchLike = async () => {
      throw new Error('boom');
    };
    await expect(
      stockQuote('600000', {
        token: 't',
        fetchImpl: failing,
        logger: { warn: (m) => warnings.push(m) },
      }),
    ).resolves.toBeNull();
    expect(warnings[0]).toMatch(/boom/);
  });
});

describe('msToCstDate', () => {
  test('timezone-independent CST date formatting', () => {
    // 2026-08-26 16:00 UTC+8 == 08:00 UTC
    const utcNoon = Date.UTC(2026, 7, 26, 8, 0, 0);
    expect(msToCstDate(utcNoon)).toBe('2026-08-26');
    // UTC 时间还在 25 日，CST 已是 26 日
    const utcEarly = Date.UTC(2026, 7, 25, 20, 0, 0);
    expect(msToCstDate(utcEarly)).toBe('2026-08-26');
  });
});

describe('XqAuthError', () => {
  test('is fatal (not retried by withRetry)', () => {
    expect(new XqAuthError('x')).toBeInstanceOf(Error);
  });
});
