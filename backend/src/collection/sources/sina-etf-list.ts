import { CollectionError } from '../errors';
import { fetchText, FetchLike, withRetry, RetryOptions } from '../http';
import { ListOptions } from './tencent-stock-list';

// 新浪 jsonp 壳里的回调名是固定字符串，akshare 同款
const LIST_URL =
  "https://vip.stock.finance.sina.com.cn/quotes_service/api/jsonp.php/" +
  "IO.XSRV2.CallbackList%5B'da_yPT46_Ll7K6WD'%5D/Market_Center.getHQNodeDataSimple";

export interface EtfListItem {
  code: string;
  name: string;
  /** 无 sh/sz 前缀时为 null（新号段不依赖号段规则）。 */
  market: 'SH' | 'SZ' | null;
}

interface RawEtfItem {
  symbol?: string;
  name?: string;
}

/** 新浪 ETF 列表（node=etf_hq_fund）。剥掉 jsonp 壳后为标准 JSON 数组。 */
export async function listEtfs(opts: ListOptions = {}): Promise<EtfListItem[]> {
  return withRetry(async () => {
    const url =
      `${LIST_URL}?page=1&num=5000&sort=symbol&asc=0&node=etf_hq_fund` +
      '&%5Bobject%20HTMLDivElement%5D=qvvne';
    const text = await fetchText(url, { fetchImpl: opts.fetchImpl });
    // 回调名形如 CallbackList['xxx']，含 '['，不能用 indexOf('[') 剥壳；
    // 锚定结尾取最外层括号内的 JSON 数组
    const match = text.match(/\(\s*(\[.*\])\s*\)\s*;?\s*$/s);
    if (!match) {
      throw new CollectionError('sina etf list jsonp malformed');
    }
    let parsed: RawEtfItem[];
    try {
      parsed = JSON.parse(match[1]);
    } catch (e) {
      throw new CollectionError(
        'sina etf list parse failed: ' + (e instanceof Error ? e.message : String(e)),
      );
    }
    if (!Array.isArray(parsed) || parsed.length === 0) {
      throw new CollectionError('sina etf list empty');
    }
    return parsed.map((item) => {
      const raw = String(item.symbol ?? '');
      const prefix = raw.slice(0, 2);
      if (prefix === 'sh' || prefix === 'sz') {
        return {
          code: raw.slice(2),
          name: String(item.name ?? ''),
          market: prefix === 'sh' ? ('SH' as const) : ('SZ' as const),
        };
      }
      return { code: raw, name: String(item.name ?? ''), market: null };
    });
  }, opts.retry);
}
