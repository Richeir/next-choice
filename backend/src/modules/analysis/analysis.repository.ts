import { Inject, Injectable } from '@nestjs/common';
import { DATABASE_SERVICE, DatabaseService } from '../../database/database.service';
import { SecurityType } from '../kline/kline.repository';
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
  /** 5 维得分 JSON（trend/momentum/valuation/volume/stability）。 */
  dims: string | null;
  /** 本次分析所用 LLM 模型；技术面降级时为 null。 */
  model: string | null;
  /** 提示词模板版本（模板 SHA-1 前 8 位）；技术面降级时为 null。 */
  promptVersion: string | null;
}

/** 数值型回填字段（其余 industry/fullName/category/manager 按字符串校验）。 */
const NUMERIC_SRCS = new Set(['lastAmount', 'pb', 'totalMarketCap', 'high52w', 'low52w', 'fundScale']);

/** 字符串回填字段的最大长度（防 LLM 幻觉超长文本）。 */
const MAX_STRLEN: Record<string, number> = {
  industry: 100,
  fullName: 200,
  category: 100,
  manager: 200,
};

/**
 * LLM 回填值校验：字符串字段须为字符串、非空且不超长；
 * 数值字段须为有限数值，52 周高低须为正，其余非负。
 * 校验不过的字段直接丢弃，不落库。
 */
export function isValidBackfillValue(src: string, value: unknown): boolean {
  if (NUMERIC_SRCS.has(src)) {
    if (typeof value !== 'number' || !Number.isFinite(value)) return false;
    if (src === 'high52w' || src === 'low52w') return value > 0;
    return value >= 0;
  }
  if (typeof value !== 'string') return false;
  const trimmed = value.trim();
  return trimmed.length > 0 && trimmed.length <= (MAX_STRLEN[src] ?? 100);
}

function isEmpty(value: unknown): boolean {
  return value === null || value === undefined || value === '';
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
            note, llm_analysis, dims, model, prompt_version)
         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
         ON CONFLICT(code, date) DO UPDATE SET
           score = excluded.score, signal = excluded.signal, rating = excluded.rating,
           is_worth_buying = excluded.is_worth_buying, hold_days = excluded.hold_days,
           ma5 = excluded.ma5, ma20 = excluded.ma20, ma60 = excluded.ma60,
           trend = excluded.trend, momentum_20 = excluded.momentum_20,
           volatility_20 = excluded.volatility_20, volume_ratio = excluded.volume_ratio,
           note = excluded.note, llm_analysis = excluded.llm_analysis,
           dims = excluded.dims, model = excluded.model, prompt_version = excluded.prompt_version`,
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
        row.dims,
        row.model,
        row.promptVersion,
      );
  }

  /**
   * 用 LLM 结果回填基础信息表字段。
   * 只回填空字段（NULL / 空串），已有值不覆盖；写入值须通过 isValidBackfillValue
   * 校验；回填时记录 llm_backfill_at 时间戳，便于追溯与清理。
   */
  backfillInfo(type: SecurityType, code: string, llm: LlmResult): void {
    const table = this.infoTableFor(type);
    const existing = this.getInfo(type, code);
    if (!existing) return;

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
      if (!isEmpty(existing[col])) continue; // 已有值则跳过，不覆盖
      const value = llm[src as keyof LlmResult];
      if (value === undefined) continue;
      if (!isValidBackfillValue(src, value)) continue; // 校验不过则丢弃
      sets.push(`${col} = ?`);
      params.push(value);
    }
    if (sets.length === 0) return;

    sets.push('llm_backfill_at = ?');
    params.push(new Date().toISOString());
    params.push(code);
    this.db
      .getConnection()
      .prepare(`UPDATE ${table} SET ${sets.join(', ')} WHERE code = ?`)
      .run(...params);
  }
}
