import { wanToYuan } from '../codes';
import { CollectionError } from '../errors';
import { fetchText, FetchLike, withRetry, RetryOptions } from '../http';
import { ListOptions } from './tencent-stock-list';

// 新浪开放式基金规模表（覆盖全部开放式基金，含 ETF）
const SCALE_URL =
  "http://vip.stock.finance.sina.com.cn/fund_center/data/jsonp.php/" +
  "IO.XSRV2.CallbackList%5B'J2cW8KXheoWKdSHc'%5D/NetValueReturn_Service.NetValueReturnOpen";

/** code -> { fund_scale(元), manager, ipo_date }（对齐 fund_scale_map）。 */
export interface FundScaleInfo {
  fund_scale: number | null;
  manager: string | null;
  ipo_date: string | null;
}

export type FundScaleMap = Record<string, FundScaleInfo>;

interface RawScaleItem {
  symbol?: unknown;
  zmjgm?: unknown;
  jjjl?: unknown;
  clrq?: unknown;
}

/**
 * 新浪基金规模表：type2=2（股票型）单页 num=10000 已覆盖全量（total_num≈6919）。
 * symbol 上游是数字（如 510300），与 Python str() 一致转字符串作键。
 */
export async function fundScaleMap(opts: ListOptions = {}): Promise<FundScaleMap> {
  return withRetry(async () => {
    const url =
      `${SCALE_URL}?page=1&num=10000&sort=zmjgm&asc=0&ccode=&type2=2&type3=`;
    const text = await fetchText(url, { fetchImpl: opts.fetchImpl });
    const begin = text.indexOf('{');
    const end = text.lastIndexOf('}');
    if (begin === -1 || end <= begin) {
      throw new CollectionError('sina fund scale jsonp malformed');
    }
    let parsed: { total_num?: unknown; data?: RawScaleItem[] };
    try {
      parsed = JSON.parse(text.slice(begin, end + 1));
    } catch (e) {
      throw new CollectionError(
        'sina fund scale parse failed: ' + (e instanceof Error ? e.message : String(e)),
      );
    }
    const data = parsed.data;
    if (!Array.isArray(data) || data.length === 0) {
      throw new CollectionError('sina fund scale empty');
    }
    const out: FundScaleMap = {};
    for (const item of data) {
      const clrq = item.clrq == null ? '' : String(item.clrq);
      out[String(item.symbol)] = {
        fund_scale: wanToYuan(item.zmjgm),
        manager: item.jjjl == null ? null : String(item.jjjl),
        ipo_date: clrq === '' ? null : clrq.slice(0, 10),
      };
    }
    return out;
  }, opts.retry);
}
