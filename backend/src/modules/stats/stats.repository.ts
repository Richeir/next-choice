import { Inject, Injectable } from '@nestjs/common';
import { DATABASE_SERVICE, DatabaseService } from '../../database/database.service';

export interface StatsRow {
  stockCnt: number;
  etfCnt: number;
  analyzedCnt: number;
  analyzedTimes: number;
}

@Injectable()
export class StatsRepository {
  constructor(
    @Inject(DATABASE_SERVICE) private readonly db: DatabaseService,
  ) {}

  getStats(): StatsRow {
    const row = this.db
      .getConnection()
      .prepare(
        `SELECT
           (SELECT COUNT(*) FROM stock_info) AS stock_cnt,
           (SELECT COUNT(*) FROM etf_info) AS etf_cnt,
           (SELECT COUNT(DISTINCT code) FROM stock_analysis)
             + (SELECT COUNT(DISTINCT code) FROM etf_analysis) AS analyzed_cnt,
           (SELECT COUNT(*) FROM stock_analysis)
             + (SELECT COUNT(*) FROM etf_analysis) AS analyzed_times`,
      )
      .get() as {
      stock_cnt: number;
      etf_cnt: number;
      analyzed_cnt: number;
      analyzed_times: number;
    };
    return {
      stockCnt: Number(row.stock_cnt),
      etfCnt: Number(row.etf_cnt),
      analyzedCnt: Number(row.analyzed_cnt),
      analyzedTimes: Number(row.analyzed_times),
    };
  }
}
