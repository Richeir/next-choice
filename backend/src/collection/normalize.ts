import { DecodedBar } from './sina-decrypt';

/** 原始 bar：解码产物 + 可选的换手率来源。 */
export interface RawBar extends DecodedBar {}

/** 标准化 K 线行，字段与 scripts/akshare_source.py::KLINE_COLS 一致。 */
export interface KlineRow {
  date: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  preclose: number | null;
  volume: number | null;
  amount: number | null;
  /** 换手率（小数）；无股本数据源时为 null。 */
  turn: number | null;
  pctChg: number | null;
}

export interface NormalizeOptions {
  /**
   * true：直接采用解码自带 prevclose（ETF 路径，akshare 保留该列）；
   * false（默认）：preclose 取上一根 close（股票路径，akshare 删除该列后 shift）。
   */
  useDecodedPreclose?: boolean;
  /** 换手率解析器：按日期返回 volume 的分母（股本，股），无数据返回 null。 */
  turnAt?: (date: string) => number | null;
}

/**
 * 原始日 K -> KLINE_COLS 标准化：
 * 按 date 升序；preclose 见上；pctChg=(close/preclose-1)*100；
 * turn 由 turnAt 提供，缺失为 null。语义对齐 _normalize_daily。
 */
export function normalizeDaily(
  bars: readonly RawBar[],
  opts: NormalizeOptions = {},
): KlineRow[] {
  const sorted = [...bars].sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  const rows: KlineRow[] = [];
  let prevClose: number | null = null;
  for (const bar of sorted) {
    const preclose = opts.useDecodedPreclose
      ? bar.prevclose
      : prevClose;
    const pctChg =
      preclose !== null && bar.close !== null && preclose !== 0
        ? ((bar.close - preclose) / preclose) * 100
        : null;
    const shares = opts.turnAt?.(bar.date) ?? null;
    const turn =
      shares !== null && shares !== 0 && bar.volume !== null
        ? bar.volume / shares
        : null;
    rows.push({
      date: bar.date,
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
      preclose,
      volume: bar.volume,
      amount: bar.amount,
      turn,
      pctChg,
    });
    prevClose = bar.close;
  }
  return rows;
}

/** 闭区间 [start, end] 日期过滤（YYYY-MM-DD 字典序即可比较）。 */
export function filterByDate(
  rows: readonly KlineRow[],
  start: string,
  end: string,
): KlineRow[] {
  return rows.filter((r) => r.date >= start && r.date <= end);
}
