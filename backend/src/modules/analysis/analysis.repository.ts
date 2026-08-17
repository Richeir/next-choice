import { Inject, Injectable } from '@nestjs/common';
import { DATABASE_SERVICE, DatabaseService } from '../../database/database.service';
import { SecurityType } from '../kline/kline.repository';
import { TechnicalResult } from './technical-analysis.service';
import { LlmResult } from './llm.service';

export interface AnalysisInsert {
  date: string;
  score: number;
  signal: string;
  rating: string;
  isWorthBuying: number;
  holdDays: number;
  ma5: number | null;
  ma20: number | null;
  ma60: number | null;
  trend: string;
  momentum20: number | null;
  volatility20: number | null;
  volumeRatio: number | null;
  note: string;
  llmAnalysis: string | null;
}

@Injectable()
export class AnalysisRepository {
  constructor(
    @Inject(DATABASE_SERVICE) private readonly db: DatabaseService,
  ) {}

  infoTableFor(type: SecurityType): string {
    return type === 'stock' ? 'stock_info' : 'etf_info';
  }

  analysisTableFor(type: SecurityType): string {
    return `${type}_analysis`;
  }

  exists(type: SecurityType, code: string): boolean {
    const row = this.db
      .getConnection()
      .prepare(`SELECT code FROM ${this.infoTableFor(type)} WHERE code = ?`)
      .get(code);
    return !!row;
  }

  getInfo(type: SecurityType, code: string): Record<string, unknown> | undefined {
    return this.db
      .getConnection()
      .prepare(`SELECT * FROM ${this.infoTableFor(type)} WHERE code = ?`)
      .get(code) as Record<string, unknown> | undefined;
  }

  insertAnalysis(type: SecurityType, code: string, row: AnalysisInsert): void {
    const table = this.analysisTableFor(type);
    this.db
      .getConnection()
      .prepare(
        `INSERT INTO ${table}
           (code, date, score, signal, rating, is_worth_buying, hold_days,
            ma5, ma20, ma60, trend, momentum_20, volatility_20, volume_ratio,
            note, llm_analysis)
         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
         ON CONFLICT(code, date) DO UPDATE SET
           score = excluded.score, signal = excluded.signal, rating = excluded.rating,
           is_worth_buying = excluded.is_worth_buying, hold_days = excluded.hold_days,
           ma5 = excluded.ma5, ma20 = excluded.ma20, ma60 = excluded.ma60,
           trend = excluded.trend, momentum_20 = excluded.momentum_20,
           volatility_20 = excluded.volatility_20, volume_ratio = excluded.volume_ratio,
           note = excluded.note, llm_analysis = excluded.llm_analysis`,
      )
      .run(
        code,
        row.date,
        row.score,
        row.signal,
        row.rating,
        row.isWorthBuying,
        row.holdDays,
        row.ma5,
        row.ma20,
        row.ma60,
        row.trend,
        row.momentum20,
        row.volatility20,
        row.volumeRatio,
        row.note,
        row.llmAnalysis,
      );
  }

  /** 用 LLM 结果回填基础信息表字段（可空字段）。 */
  backfillInfo(type: SecurityType, code: string, llm: LlmResult): void {
    const table = this.infoTableFor(type);
    const sets: string[] = [];
    const params: unknown[] = [];
    const mapping: Record<string, string> =
      type === 'stock'
        ? {
            industry: 'industry',
            lastAmount: 'last_amount',
            pb: 'pb',
            fullName: 'full_name',
            totalMarketCap: 'total_market_cap',
            high52w: 'high_52w',
            low52w: 'low_52w',
          }
        : {
            category: 'category',
            manager: 'manager',
            fundScale: 'fund_scale',
          };
    for (const [src, col] of Object.entries(mapping)) {
      if (llm[src as keyof LlmResult] !== undefined) {
        sets.push(`${col} = ?`);
        params.push(llm[src as keyof LlmResult]);
      }
    }
    if (sets.length === 0) return;
    params.push(code);
    this.db
      .getConnection()
      .prepare(`UPDATE ${table} SET ${sets.join(', ')} WHERE code = ?`)
      .run(...params);
  }
}
