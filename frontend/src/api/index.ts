import { http } from './client';
import type {
  AnalysisItem,
  EtfDetail,
  EtfListItem,
  KlineItem,
  ListParams,
  Paged,
  Stats,
  StockDetail,
  StockListItem,
} from './types';

export async function getStats(): Promise<Stats> {
  const { data } = await http.get<Stats>('/stats');
  return data;
}

export async function getStocks(params: ListParams): Promise<Paged<StockListItem>> {
  const { data } = await http.get<Paged<StockListItem>>('/stocks', { params });
  return data;
}

export async function getEtfs(params: ListParams): Promise<Paged<EtfListItem>> {
  const { data } = await http.get<Paged<EtfListItem>>('/etfs', { params });
  return data;
}

export async function getStockDetail(code: string): Promise<StockDetail> {
  const { data } = await http.get<StockDetail>(`/stocks/${code}`);
  return data;
}

export async function getEtfDetail(code: string): Promise<EtfDetail> {
  const { data } = await http.get<EtfDetail>(`/etfs/${code}`);
  return data;
}

export async function getStockAnalysis(code: string): Promise<Paged<AnalysisItem>> {
  const { data } = await http.get<Paged<AnalysisItem>>(`/stocks/${code}/analysis`);
  return data;
}

export async function getEtfAnalysis(code: string): Promise<Paged<AnalysisItem>> {
  const { data } = await http.get<Paged<AnalysisItem>>(`/etfs/${code}/analysis`);
  return data;
}

export interface AnalyzeResponse {
  accepted: boolean;
  jobId: string;
}

export type JobStatus = 'pending' | 'running' | 'done' | 'failed';

export interface JobResponse {
  jobId: string;
  status: JobStatus;
  result: unknown;
  error?: string;
}

/** 触发对某只标的的异步分析，返回 jobId 供轮询。 */
export async function analyze(kind: 'stock' | 'etf', code: string): Promise<AnalyzeResponse> {
  const base = kind === 'stock' ? '/stocks' : '/etfs';
  const { data } = await http.post<AnalyzeResponse>(`${base}/${code}/analyze`);
  return data;
}

/** 查询分析任务状态。 */
export async function getJob(jobId: string): Promise<JobResponse> {
  const { data } = await http.get<JobResponse>(`/jobs/${jobId}`);
  return data;
}

export async function getKline(
  kind: 'stock' | 'etf',
  code: string,
  params: { frequency?: string; adjust?: string; limit?: number },
): Promise<KlineItem[]> {
  const base = kind === 'stock' ? '/stocks' : '/etfs';
  const { data } = await http.get<{ items: KlineItem[] }>(`${base}/${code}/kline`, {
    params: { frequency: 'daily', adjust: 'qfq', ...params },
  });
  return data.items ?? [];
}
