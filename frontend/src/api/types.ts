/** 与 doc/api-design.md 对应的响应类型（camelCase） */

export interface Stats {
  stockCnt: number;
  etfCnt: number;
  /** 股票 + ETF 合计；分品种占比请用 stockAnalyzedCnt / etfAnalyzedCnt */
  analyzedCnt: number;
  stockAnalyzedCnt: number;
  etfAnalyzedCnt: number;
  analyzedTimes: number;
  /** 全库最新交易日（顶栏“数据日期”） */
  lastTradeDate: string | null;
}

export interface AnalysisSummary {
  date: string;
  rating: string;
  score: number;
  signal: string;
}

export interface StockListItem {
  code: string;
  codeName: string;
  market: string;
  industry: string | null;
  fullName: string | null;
  lastTradeDate: string | null;
  lastClose: number | null;
  lastPctChg: number | null;
  lastAmount: number | null;
  peTtm: number | null;
  pb: number | null;
  totalMarketCap: number | null;
  high52w: number | null;
  low52w: number | null;
  analysis: AnalysisSummary | null;
}

export interface EtfListItem {
  code: string;
  codeName: string;
  market: string;
  category: string | null;
  manager: string | null;
  lastTradeDate: string | null;
  /** spec 字段名；后端在 lastClose 为 null 时不返回该字段 */
  nav?: number | null;
  lastClose?: number | null;
  lastPctChg: number | null;
  fundScale: number | null;
  analysis: AnalysisSummary | null;
}

export interface Paged<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
}

export interface StockDetail {
  code: string;
  codeName: string;
  fullName: string | null;
  market: string;
  type: string;
  ipoDate: string | null;
  outDate: string | null;
  status: string;
  industry: string | null;
  lastTradeDate: string | null;
  lastClose: number | null;
  lastPctChg: number | null;
  lastAmount: number | null;
  peTtm: number | null;
  pb: number | null;
  totalMarketCap: number | null;
  high52w: number | null;
  low52w: number | null;
}

export interface EtfDetail {
  code: string;
  codeName: string;
  market: string;
  type: string;
  ipoDate: string | null;
  outDate: string | null;
  status: string;
  category: string | null;
  manager: string | null;
  lastTradeDate: string | null;
  nav?: number | null;
  lastClose?: number | null;
  lastPctChg: number | null;
  fundScale: number | null;
  high52w?: number | null;
  low52w?: number | null;
}

export interface AnalysisItem {
  code?: string;
  date: string;
  score: number;
  signal: string;
  rating: string;
  isWorthBuying: number;
  holdDays: number;
  ma5?: number | null;
  ma20?: number | null;
  ma60?: number | null;
  trend: string | null;
  momentum20: number | null;
  volatility20: number | null;
  volumeRatio: number | null;
  note: string | null;
  llmAnalysis: string | null;
}

export interface KlineItem {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  amount: number;
}

export type ListParams = Record<string, string | number | undefined>;
