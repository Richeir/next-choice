import { Inject, Injectable } from '@nestjs/common';
import { DATABASE_SERVICE, DatabaseService } from '../../database/database.service';

export type SecurityType = 'stock' | 'etf';
export type KlineFrequency = 'daily' | 'weekly' | 'monthly';
/** 前复权 / 不复权 → adjustflag 映射。 */
export const ADJUST_MAP: Record<string, string> = { qfq: '2', raw: '3' };

export interface KlineQuery {
  type: SecurityType;
  code: string;
  frequency: KlineFrequency;
  adjustflag: string;
  limit?: number;
  start?: string;
  end?: string;
}

const MAX_LIMIT = 5000;

@Injectable()
export class KlineRepository {
  constructor(
    @Inject(DATABASE_SERVICE) private readonly db: DatabaseService,
  ) {}

  list(q: KlineQuery): Record<string, unknown>[] {
    const table = `${q.type}_kline_${q.frequency}`;
    const clauses = ['code = ?', 'adjustflag = ?'];
    const params: unknown[] = [q.code, q.adjustflag];
    if (q.start) {
      clauses.push('date >= ?');
      params.push(q.start);
    }
    if (q.end) {
      clauses.push('date <= ?');
      params.push(q.end);
    }
    const limit = Math.min(MAX_LIMIT, Math.max(1, q.limit ?? 250));

    const sql = `SELECT date, open, high, low, close, volume, amount
                 FROM ${table}
                 WHERE ${clauses.join(' AND ')}
                 ORDER BY date DESC LIMIT ?`;
    const rows = this.db.getConnection().prepare(sql).all(...params, limit) as Record<
      string,
      unknown
    >[];
    // 升序返回（时间正序）
    return rows.reverse();
  }
}
