import { numOrNull, toXqCode } from '../codes';
import { XqAuthError } from '../errors';
import { FetchLike } from '../http';

/**
 * 雪球 token 生命周期与 Python 侧一致（PR #56）：
 * 内置 token 已过期（400016），需从浏览器拷贝 xq_a_token 注入 XQ_TOKEN。
 */

export function xqTokenFromEnv(env: NodeJS.ProcessEnv = process.env): string | null {
  const tok = (env.XQ_TOKEN ?? '').trim();
  return tok === '' ? null : tok;
}

export interface XqLogger {
  warn: (message: string) => void;
}

export interface XqOptions {
  /** 覆盖环境变量注入的 token（测试用）。 */
  token?: string | null;
  fetchImpl?: FetchLike;
  logger?: XqLogger;
}

export interface StockBasicInfo {
  full_name: string | null;
  industry: string | null;
  ipo_date: string | null;
}

export interface StockQuoteInfo {
  pb: number | null;
  high_52w: number | null;
  low_52w: number | null;
  total_market_cap: number | null;
}

const IPHONE_UA =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) ' +
  'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1';

let tokenHintShown = false;

/** 测试辅助：重置一次性提示的状态。 */
export function resetXqTokenHint(): void {
  tokenHintShown = false;
}

function tokenHintSuffix(token: string | null): string {
  if (tokenHintShown) return '';
  tokenHintShown = true;
  return token === null
    ? '（akshare 内置 xq_a_token 已失效：请从浏览器登录雪球后' +
        '将 cookie 里的 xq_a_token 写入环境变量 XQ_TOKEN）'
    : '（已注入 XQ_TOKEN，若持续 400016 说明该 token 也已过期）';
}

function collectSetCookies(res: Response): string[] {
  const headersWithGetSetCookie = res.headers as Headers & {
    getSetCookie?: () => string[];
  };
  if (typeof headersWithGetSetCookie.getSetCookie === 'function') {
    return headersWithGetSetCookie.getSetCookie();
  }
  const single = res.headers.get('set-cookie');
  return single ? [single] : [];
}

/**
 * 雪球 API GET：先访问首页拿风控 cookie，再带 xq_a_token 与之拼接请求
 * （等价 akshare 的 session 两段式）。返回解析后的 JSON。
 */
async function xqApiGet(
  pathWithQuery: string,
  token: string | null,
  fetchImpl: FetchLike,
): Promise<Record<string, unknown>> {
  const baseHeaders: Record<string, string> = {
    'User-Agent': IPHONE_UA,
    cookie: token === null ? '' : `xq_a_token=${token};`,
  };
  const warmup = await fetchImpl('https://xueqiu.com', { headers: baseHeaders });
  const warmupCookies = collectSetCookies(warmup)
    .map((c) => c.split(';')[0])
    .filter(Boolean);
  const cookie = warmupCookies.length
    ? `${baseHeaders.cookie}${warmupCookies.join('; ')}`
    : baseHeaders.cookie;
  const res = await fetchImpl(`https://stock.xueqiu.com${pathWithQuery}`, {
    headers: { ...baseHeaders, cookie },
  });
  if (!res.ok) {
    throw new XqAuthError(`xueqiu HTTP ${res.status} for ${pathWithQuery}`);
  }
  return (await res.json()) as Record<string, unknown>;
}

async function xqFetchMapped<T>(
  pathWithQuery: string,
  opts: XqOptions,
  map: (data: Record<string, unknown>) => T,
): Promise<T | null> {
  const token = opts.token === undefined ? xqTokenFromEnv() : opts.token;
  const logger = opts.logger ?? console;
  const fetchImpl = opts.fetchImpl ?? ((url: string, init?: RequestInit) => globalThis.fetch(url, init));
  if (token === null) {
    logger.warn(`xq fetch ${pathWithQuery} failed${tokenHintSuffix(null)}`);
    return null;
  }
  try {
    const json = await xqApiGet(pathWithQuery, token, fetchImpl);
    if (!json.data) {
      throw new XqAuthError(
        `xueqiu error_code=${json.error_code} ${String(json.error_description ?? '')}`,
      );
    }
    return map(json.data as Record<string, unknown>);
  } catch (e) {
    // 对齐 _xq_kv：雪球逐只调用，失败不打断全市场循环
    logger.warn(
      `xq fetch ${pathWithQuery} failed: ${
        e instanceof Error ? e.message : String(e)
      }${tokenHintSuffix(token)}`,
    );
    return null;
  }
}

/** 毫秒时间戳 -> CST（UTC+8）YYYY-MM-DD，与时区无关。 */
export function msToCstDate(ms: number): string {
  return new Date(ms + 8 * 3600000).toISOString().slice(0, 10);
}

/** 雪球个股基本信息（F10 公司概况）。失败返回 null。 */
export async function stockBasic(
  code: string,
  opts: XqOptions = {},
): Promise<StockBasicInfo | null> {
  return xqFetchMapped(
    `/v5/stock/f10/cn/company.json?symbol=${toXqCode(code)}`,
    opts,
    (data) => {
      const industry = data.affiliate_industry;
      const listedDate = data.listed_date;
      return {
        full_name: data.org_name_cn == null ? null : String(data.org_name_cn),
        industry:
          industry && typeof industry === 'object'
            ? ((industry as { ind_name?: unknown }).ind_name == null
              ? null
              : String((industry as { ind_name?: unknown }).ind_name))
            : null,
        ipo_date:
          typeof listedDate === 'number' ? msToCstDate(listedDate) : null,
      };
    },
  );
}

/** 雪球个股实时行情。失败返回 null。 */
export async function stockQuote(
  code: string,
  opts: XqOptions = {},
): Promise<StockQuoteInfo | null> {
  return xqFetchMapped(
    `/v5/stock/quote.json?symbol=${toXqCode(code)}&extend=detail`,
    opts,
    (data) => {
      const quote = (data.quote ?? {}) as Record<string, unknown>;
      return {
        pb: numOrNull(quote.pb),
        high_52w: numOrNull(quote.high52w),
        low_52w: numOrNull(quote.low52w),
        total_market_cap: numOrNull(quote.market_capital),
      };
    },
  );
}
