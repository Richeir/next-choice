import { Inject, Injectable } from '@nestjs/common';
import { SecuritiesBase, InfoTableConfig } from './securities.base';
import { DATABASE_SERVICE, DatabaseService } from '../../../database/database.service';

const STOCK_CONFIG: InfoTableConfig = {
  infoTable: 'stock_info',
  analysisTable: 'stock_analysis',
  listColumns: [
    'code',
    'code_name',
    'market',
    'industry',
    'full_name',
    'last_trade_date',
    'last_close',
    'last_pct_chg',
    'last_amount',
    'pe_ttm',
    'pb',
    'total_market_cap',
    'high_52w',
    'low_52w',
  ],
  detailColumns: [
    'code',
    'code_name',
    'full_name',
    'market',
    'type',
    'ipoDate',
    'outDate',
    'status',
    'industry',
    'last_trade_date',
    'last_close',
    'last_pct_chg',
    'last_amount',
    'pe_ttm',
    'pb',
    'total_market_cap',
    'high_52w',
    'low_52w',
  ],
  sortFields: {
    code: 'si.code',
    codeName: 'si.code_name',
    lastClose: 'si.last_close',
    lastPctChg: 'si.last_pct_chg',
    lastAmount: 'si.last_amount',
    industry: 'si.industry',
    peTtm: 'si.pe_ttm',
    pb: 'si.pb',
    score: 'a.score',
  },
  ratingOrder:
    "WHEN 'S+' THEN 9 WHEN 'S' THEN 8 WHEN 'A+' THEN 7 WHEN 'A' THEN 6 WHEN 'B+' THEN 5 " +
    "WHEN 'B' THEN 4 WHEN 'C+' THEN 3 WHEN 'C' THEN 2 WHEN 'D' THEN 1 ELSE 0",
  filterFields: ['industry'],
};

@Injectable()
export class StockInfoRepository extends SecuritiesBase {
  constructor(
    @Inject(DATABASE_SERVICE) service: DatabaseService,
  ) {
    super(service.getConnection(), STOCK_CONFIG);
  }
}
