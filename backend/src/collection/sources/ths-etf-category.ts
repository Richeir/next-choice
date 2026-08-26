import { CollectionError, EmptyDataError } from '../errors';
import { fetchText, FetchLike, withRetry, RetryOptions } from '../http';
import { ListOptions } from './tencent-stock-list';

// 该接口仅提供 code -> 基金类型 映射，是 8 个在用接口里信息量最低的；
// 已知风险：同花顺对代理出口 IP 风控，会间歇性下发"能解析的空包"
// （PHP 序列化的 count=0 响应），因此这里做严格的空数据校验并按可重试抛出。
const THS_URL =
  'https://fund.10jqka.com.cn/data/Net/info/' +
  'ETF_rate_desc_0_1_9999_0_0_0_jsonp_g.html';

/** code -> 基金类型（如 "指数型"），对齐 etf_category_map。 */
export type EtfCategoryMap = Record<string, string>;

interface ThsPayload {
  data?: { data?: Record<string, { typename?: unknown }> };
}

/** 同花顺 ETF 类别映射。空数据/降级响应抛 EmptyDataError（可重试）。 */
export async function etfCategoryMap(opts: ListOptions = {}): Promise<EtfCategoryMap> {
  return withRetry(async () => {
    const text = await fetchText(THS_URL, { fetchImpl: opts.fetchImpl });
    // 正常响应为 "(jsonp({...}))" 形式；降级时是 PHP 序列化文本（无括号包裹）。
    // 先取最外层括号内容，再截其中最外层大括号，避免误吞回调名等噪声。
    const outer = text.match(/\(([\s\S]*)\)\s*;?\s*$/);
    const inner = outer?.[1] ?? '';
    const begin = inner.indexOf('{');
    const end = inner.lastIndexOf('}');
    if (!outer || begin === -1 || end <= begin) {
      throw new EmptyDataError(
        `ths etf category degraded response: ${text.slice(0, 80)}`,
      );
    }
    let payload: ThsPayload;
    try {
      payload = JSON.parse(inner.slice(begin, end + 1));
    } catch {
      throw new EmptyDataError(
        `ths etf category non-json response: ${text.slice(0, 80)}`,
      );
    }
    const rows = payload.data?.data;
    if (!rows || typeof rows !== 'object' || Object.keys(rows).length === 0) {
      throw new EmptyDataError('ths etf category empty dataset');
    }
    const out: EtfCategoryMap = {};
    for (const [code, row] of Object.entries(rows)) {
      out[code] = row?.typename == null ? '' : String(row.typename);
    }
    return out;
  }, opts.retry);
}
