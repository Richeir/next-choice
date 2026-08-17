import { Injectable, NotFoundException } from '@nestjs/common';
import { StockInfoRepository } from './repository/stock-info.repository';
import { EtfInfoRepository } from './repository/etf-info.repository';
import { Paginated, ListOptions } from './repository/securities.base';
import { rowToCamel } from '../../common/mapper';

export interface SecuritiesListQuery {
  keyword?: string;
  market?: string;
  industry?: string;
  category?: string;
  manager?: string;
  status?: string;
  sortBy?: string;
  order?: 'asc' | 'desc';
  page?: number;
  pageSize?: number;
}

const MAX_PAGE_SIZE = 100;
const DEFAULT_PAGE_SIZE = 20;

@Injectable()
export class SecuritiesService {
  constructor(
    private readonly stockRepo: StockInfoRepository,
    private readonly etfRepo: EtfInfoRepository,
  ) {}

  async listStocks(query: SecuritiesListQuery): Promise<Paginated<Record<string, unknown>>> {
    const opts = this.normalizeQuery(query);
    const result = this.stockRepo.list(opts);
    return {
      items: result.items.map((row) => this.mapStockListItem(row)),
      total: result.total,
      page: result.page,
      pageSize: result.pageSize,
    };
  }

  async getStockDetail(code: string): Promise<Record<string, unknown>> {
    const row = this.stockRepo.findDetail(code);
    if (!row) throw new NotFoundException(`stock ${code} not found`);
    return rowToCamel(row);
  }

  async listStockAnalysis(
    code: string,
    page: number,
    pageSize: number,
  ): Promise<Paginated<Record<string, unknown>>> {
    const result = this.stockRepo.listAnalysis(code, page, pageSize);
    return {
      items: result.items.map((row) => this.mapAnalysisRow(row)),
      total: result.total,
      page: result.page,
      pageSize: result.pageSize,
    };
  }

  async listEtfs(query: SecuritiesListQuery): Promise<Paginated<Record<string, unknown>>> {
    const opts = this.normalizeQuery(query);
    const result = this.etfRepo.list(opts);
    return {
      items: result.items.map((row) => this.mapEtfListItem(row)),
      total: result.total,
      page: result.page,
      pageSize: result.pageSize,
    };
  }

  async getEtfDetail(code: string): Promise<Record<string, unknown>> {
    const row = this.etfRepo.findDetail(code);
    if (!row) throw new NotFoundException(`etf ${code} not found`);
    const mapped = rowToCamel(row);
    if (mapped['lastClose'] != null) mapped['nav'] = mapped['lastClose'];
    return mapped;
  }

  async listEtfAnalysis(
    code: string,
    page: number,
    pageSize: number,
  ): Promise<Paginated<Record<string, unknown>>> {
    const result = this.etfRepo.listAnalysis(code, page, pageSize);
    return {
      items: result.items.map((row) => this.mapAnalysisRow(row)),
      total: result.total,
      page: result.page,
      pageSize: result.pageSize,
    };
  }

  private normalizeQuery(q: SecuritiesListQuery): ListOptions {
    const page = Math.max(1, Number(q.page) || 1);
    const pageSize = Math.min(MAX_PAGE_SIZE, Math.max(1, Number(q.pageSize) || DEFAULT_PAGE_SIZE));
    const order = q.order === 'asc' ? 'asc' : 'desc';
    return { ...q, page, pageSize, order };
  }

  private mapStockListItem(row: Record<string, unknown>): Record<string, unknown> {
    const base = this.stripAnalysisCols(rowToCamel(row));
    const analysis = this.analysisSummaryFromRow(row);
    return { ...base, analysis };
  }

  private mapEtfListItem(row: Record<string, unknown>): Record<string, unknown> {
    const base = this.stripAnalysisCols(rowToCamel(row));
    if (base['lastClose'] != null) base['nav'] = base['lastClose'];
    const analysis = this.analysisSummaryFromRow(row);
    return { ...base, analysis };
  }

  private stripAnalysisCols(obj: Record<string, unknown>): Record<string, unknown> {
    const { rating, score, signal, analysisDate, ...rest } = obj as Record<
      string,
      unknown
    >;
    return rest;
  }

  private analysisSummaryFromRow(row: Record<string, unknown>) {
    if (row.rating == null && row.score == null) return null;
    return {
      date: row.analysis_date ?? null,
      rating: row.rating ?? null,
      score: row.score ?? null,
      signal: row.signal ?? null,
    };
  }

  private mapAnalysisRow(row: Record<string, unknown>): Record<string, unknown> {
    return rowToCamel(row);
  }
}
