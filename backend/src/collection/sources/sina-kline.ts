import { CollectionError } from '../errors';
import { withRetry, FetchLike, RetryOptions, fetchText } from '../http';
import { filterByDate, KlineRow, normalizeDaily } from '../normalize';
import { decodeSinaKlines, DecodedBar } from '../sina-decrypt';
import { toSinaCode } from '../codes';

/** 与 Python 侧 _ADJUST_SINA 对齐：'3'->''（不复权），'2'->'qfq'。 */
export type SinaAdjust = '' | 'qfq';

const klcUrl = (symbol: string) =>
  `https://finance.sina.com.cn/realstock/company/${symbol}/hisdata_klc2/klc_kl.js`;

// 新浪股本变迁表（万股）；akshare 用它计算换手率 turnover。
const amountUrl = (symbol: string) =>
  'https://stock.finance.sina.com.cn/stock/api/jsonp.php/' +
  `var%20KKE_ShareAmount_${symbol}=/StockService.getAmountBySymbol` +
  `?_=20&symbol=${symbol}`;

const qfqUrl = (symbol: string) =>
  `https://finance.sina.com.cn/realstock/company/${symbol}/qfq.js`;

export interface SinaKlineOptions {
  start: string;
  end: string;
  adjust?: SinaAdjust;
  fetchImpl?: FetchLike;
  retry?: RetryOptions;
}

interface ShareEntry {
  date: string;
  /** 股数（已由万股换算为股）。 */
  shares: number;
}

/** 解析 getAmountBySymbol 的 jsonp 响应：截取最外层 [ ] 后 JSON.parse。 */
export function parseAmountJsonp(text: string): Array<{ date: string; wanShares: number }> {
  const begin = text.indexOf('[');
  const end = text.lastIndexOf(']');
  if (begin === -1 || end <= begin) {
    throw new CollectionError('sina amount jsonp malformed');
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(text.slice(begin, end + 1));
  } catch (e) {
    throw new CollectionError(
      'sina amount json parse failed: ' + (e instanceof Error ? e.message : String(e)),
    );
  }
  if (!Array.isArray(parsed)) throw new CollectionError('sina amount payload not array');
  return parsed.map((item: { date?: string; amount?: unknown }) => ({
    date: String(item.date ?? ''),
    wanShares: Number(item.amount ?? NaN),
  }));
}

/**
 * 股本 ffill 查询：某日期的有效股本 = 变更日期 <= 该日的最近一条记录；
 * 早于首条记录的日期无数据（返回 null）。
 */
export function shareResolver(entries: readonly ShareEntry[]): (date: string) => number | null {
  const sorted = [...entries].sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  return (date: string): number | null => {
    let found: number | null = null;
    for (const e of sorted) {
      if (e.date <= date && Number.isFinite(e.shares)) found = e.shares;
      else if (e.date > date) break;
    }
    return found;
  };
}

interface QfqFactor {
  date: string;
  factor: number;
}

/** 解析 qfq.js：var xxxqfq={"total":N,"data":[{"d":"...","f":"1.23"}]}。 */
export function parseQfqFactors(text: string): QfqFactor[] {
  const begin = text.indexOf('{');
  const end = text.lastIndexOf('}');
  if (begin === -1 || end <= begin) {
    throw new CollectionError('sina qfq file malformed');
  }
  let parsed: { data?: Array<{ d?: string; f?: unknown }> };
  try {
    parsed = JSON.parse(text.slice(begin, end + 1));
  } catch (e) {
    throw new CollectionError(
      'sina qfq json parse failed: ' + (e instanceof Error ? e.message : String(e)),
    );
  }
  const factors = (parsed.data ?? []).map((item) => ({
    date: String(item.d ?? ''),
    factor: Number(item.f ?? NaN),
  }));
  // qfq.js 按除权日倒序下发，统一转为升序便于指针推进
  return factors.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
}

/**
 * 前复权：price / factor（对齐 akshare qfq 分支）。
 * 早于首个除权日的 bar 无因子，按 dropna 语义丢弃；价格保留两位小数。
 */
export function applyQfqFactors(
  bars: readonly DecodedBar[],
  factors: readonly QfqFactor[],
): DecodedBar[] {
  let cursor = 0;
  let current: QfqFactor | null = null;
  const out: DecodedBar[] = [];
  for (const bar of bars) {
    while (cursor < factors.length && factors[cursor].date <= bar.date) {
      current = factors[cursor];
      cursor++;
    }
    if (!current || !Number.isFinite(current.factor) || current.factor === 0) continue;
    const div = (v: number | null): number | null =>
      v === null ? null : Math.round((v / current!.factor) * 100) / 100;
    out.push({
      ...bar,
      open: div(bar.open) as number,
      high: div(bar.high) as number,
      low: div(bar.low) as number,
      close: div(bar.close) as number,
    });
  }
  return out;
}

async function fetchDecodedBars(
  symbol: string,
  opts: SinaKlineOptions,
): Promise<DecodedBar[]> {
  return withRetry(async () => {
    const text = await fetchText(klcUrl(symbol), { fetchImpl: opts.fetchImpl });
    return decodeSinaKlines(text); // EmptyDataError 可重试
  }, opts.retry);
}

/** 股票日 K（新浪源）。adjust 仅支持 '' 与 'qfq'。 */
export async function stockDaily(
  code: string,
  opts: SinaKlineOptions,
): Promise<KlineRow[]> {
  const symbol = toSinaCode(code);
  const adjust = opts.adjust ?? '';
  if (adjust !== '' && adjust !== 'qfq') {
    throw new CollectionError(`unsupported sina adjust: ${adjust}`);
  }
  return withRetry(async () => {
    let bars = await fetchDecodedBars(symbol, opts);
    // 对齐 akshare：股票路径删除解密 prevclose，标准化时改用 shift(1)
    bars = bars.map((b) => ({ ...b, prevclose: null }));
    if (adjust === 'qfq') {
      const text = await fetchText(qfqUrl(symbol), { fetchImpl: opts.fetchImpl });
      bars = applyQfqFactors(bars, parseQfqFactors(text));
    }
    const entries = await withRetry(async () => {
      const raw = await fetchText(amountUrl(symbol), { fetchImpl: opts.fetchImpl });
      return parseAmountJsonp(raw).map((e) => ({
        date: e.date,
        shares: e.wanShares * 1e4,
      }));
    }, opts.retry);
    const rows = normalizeDaily(bars, { turnAt: shareResolver(entries) });
    return filterByDate(rows, opts.start, opts.end);
  }, opts.retry);
}

/** ETF 日 K（新浪源，仅不复权；接口返回全量历史后本地按日期过滤）。 */
export async function etfDaily(
  code: string,
  opts: Omit<SinaKlineOptions, 'adjust'>,
): Promise<KlineRow[]> {
  const symbol = toSinaCode(code);
  return withRetry(async () => {
    const bars = await fetchDecodedBars(symbol, opts);
    const rows = normalizeDaily(bars, { useDecodedPreclose: true });
    return filterByDate(rows, opts.start, opts.end);
  }, opts.retry);
}
