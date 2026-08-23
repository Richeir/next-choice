import { Inject, Injectable } from '@nestjs/common';
import { DATABASE_SERVICE, DatabaseService } from '../../database/database.service';

export interface StatsRow {
  stockCnt: number;
  etfCnt: number;
  /** 股票 + ETF 的已分析标的合计（保留兼容，占比计算请用下面两个分项）。 */
  analyzedCnt: number;
  stockAnalyzedCnt: number;
  etfAnalyzedCnt: number;
  analyzedTimes: number;
  /** 全库最新交易日；无数据时为 null。前端顶栏“数据日期”直接用它。 */
  lastTradeDate: string | null;
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
           (SELECT COUNT(DISTINCT code) FROM stock_analysis) AS stock_analyzed_cnt,
           (SELECT COUNT(DISTINCT code) FROM etf_analysis) AS etf_analyzed_cnt,
           (SELECT COUNT(*) FROM stock_analysis)
             + (SELECT COUNT(*) FROM etf_analysis) AS analyzed_times,
           (SELECT MAX(d) FROM (
              SELECT MAX(last_trade_date) AS d FROM stock_info
              UNION ALL
              SELECT MAX(last_trade_date) FROM etf_info
            )) AS last_trade_date`,
      )
      .get() as {
      stock_cnt: number;
      etf_cnt: number;
      stock_analyzed_cnt: number;
      etf_analyzed_cnt: number;
      analyzed_times: number;
      last_trade_date: string | null;
    };
    const stockAnalyzedCnt = Number(row.stock_analyzed_cnt);
    const etfAnalyzedCnt = Number(row.etf_analyzed_cnt);
    return {
      stockCnt: Number(row.stock_cnt),
      etfCnt: Number(row.etf_cnt),
      analyzedCnt: stockAnalyzedCnt + etfAnalyzedCnt,
      stockAnalyzedCnt,
      etfAnalyzedCnt,
      analyzedTimes: Number(row.analyzed_times),
      lastTradeDate: row.last_trade_date ?? null,
    };
  }
}
