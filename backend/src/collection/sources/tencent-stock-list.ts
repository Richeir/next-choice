import { numOrNull, stripPrefix, wanToYuan, yiToYuan } from '../codes';
import { RetryableError } from '../errors';
import { fetchText, FetchLike, withRetry, RetryOptions } from '../http';

const RANK_URL = 'https://proxy.finance.qq.com/cgi/cgi-bin/rank/hs/getBoardRankList';
const PAGE_SIZE = 200;

export interface StockListItem {
  code: string;
  name: string;
  pe_ttm: number | null;
  total_market_cap: number | null;
  last_close: number | null;
  last_pct_chg: number | null;
  last_amount: number | null;
}

interface RankItem {
  code?: string;
  name?: string;
  pe_ttm?: unknown;
  zsz?: unknown;
  zxj?: unknown;
  zdf?: unknown;
  turnover?: unknown;
}

export interface ListOptions {
  fetchImpl?: FetchLike;
  retry?: RetryOptions;
}

/**
 * 腾讯全市场 A 股实时行情（分页拉全量）。
 * 失败抛异常：列表是全量刷新的前提，不应静默降级（对齐 list_stocks）。
 */
export async function listStocks(opts: ListOptions = {}): Promise<StockListItem[]> {
  return withRetry(async () => {
    const items: RankItem[] = [];
    let total: number | null = null;
    let page = 0;
    while (total === null || items.length < total) {
      const url =
        `${RANK_URL}?_appver=11.17.0&board_code=aStock` +
        `&sort_type=price&direct=down&offset=${page * PAGE_SIZE}&count=${PAGE_SIZE}`;
      let json: { data?: { total?: unknown; rank_list?: RankItem[] } };
      // 仅把解析失败视为可重试；fetchText 的网络/HTTP 错误自行分类
      const text = await fetchText(url, { fetchImpl: opts.fetchImpl });
      try {
        json = JSON.parse(text);
      } catch (e) {
        throw new RetryableError(
          'tencent rank response invalid: ' + (e instanceof Error ? e.message : String(e)),
        );
      }
      total = Number(json?.data?.total);
      if (!Number.isFinite(total)) {
        throw new RetryableError('tencent rank response missing data.total');
      }
      const list = json?.data?.rank_list;
      if (!Array.isArray(list) || list.length === 0) {
        // 中途空页属于限流/风控的"能解析的空包"，必须重试而不是当全量收尾
        if (items.length < total) throw new RetryableError('tencent rank_list empty mid-pagination');
        break;
      }
      items.push(...list);
      page++;
      if (page > Math.ceil(total / PAGE_SIZE) + 5) {
        throw new RetryableError('tencent pagination does not converge');
      }
    }
    const seen = new Set<string>();
    const out: StockListItem[] = [];
    for (const r of items) {
      const code = r.code ? stripPrefix(r.code) : '';
      // 对齐 pandas drop_duplicates(subset='code')：保留首次出现
      if (!code || seen.has(code)) continue;
      seen.add(code);
      out.push({
        code,
        name: r.name ?? '',
        pe_ttm: numOrNull(r.pe_ttm),
        total_market_cap: yiToYuan(r.zsz),
        last_close: numOrNull(r.zxj),
        last_pct_chg: numOrNull(r.zdf),
        last_amount: wanToYuan(r.turnover),
      });
    }
    return out;
  }, opts.retry);
}
