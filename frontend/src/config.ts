/** 全局可配置项（对应 doc/frontend/pages.md §0） */
export const BANNER_TEXT = '生存是第一要务';

/** 数据日期兜底值：优先取接口返回的最新交易日，取不到时显示该值 */
export const FALLBACK_DATA_DATE = '—';

/** 每页条数（列表页） */
export const PAGE_SIZE = 20;

/** K 线区间 -> 交易日条数 */
export const KLINE_RANGES = [
  { key: '1M', label: '1M', limit: 21 },
  { key: '3M', label: '3M', limit: 63 },
  { key: '6M', label: '6M', limit: 126 },
  { key: '1Y', label: '1Y', limit: 250 },
  { key: '3Y', label: '3Y', limit: 750 },
  { key: '5Y', label: '5Y', limit: 1250 },
] as const;

export const DEFAULT_KLINE_RANGE = '6M';
