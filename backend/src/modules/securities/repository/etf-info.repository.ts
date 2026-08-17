import { Inject, Injectable } from '@nestjs/common';
import { SecuritiesBase, InfoTableConfig } from './securities.base';
import { DATABASE_SERVICE, DatabaseService } from '../../../database/database.service';

const ETF_CONFIG: InfoTableConfig = {
  infoTable: 'etf_info',
  analysisTable: 'etf_analysis',
  listColumns: [
    'code',
    'code_name',
    'market',
    'category',
    'manager',
    'last_trade_date',
    'last_close',
    'last_pct_chg',
    'fund_scale',
  ],
  detailColumns: [
    'code',
    'code_name',
    'market',
    'type',
    'ipoDate',
    'outDate',
    'status',
    'category',
    'manager',
    'last_trade_date',
    'last_close',
    'last_pct_chg',
    'fund_scale',
  ],
  sortFields: {
    code: 'si.code',
    codeName: 'si.code_name',
    nav: 'si.last_close',
    lastPctChg: 'si.last_pct_chg',
    fundScale: 'si.fund_scale',
    score: 'a.score',
  },
  ratingOrder:
    "WHEN 'S+' THEN 9 WHEN 'S' THEN 8 WHEN 'A+' THEN 7 WHEN 'A' THEN 6 WHEN 'B+' THEN 5 " +
    "WHEN 'B' THEN 4 WHEN 'C+' THEN 3 WHEN 'C' THEN 2 WHEN 'D' THEN 1 ELSE 0",
  filterFields: ['category', 'manager'],
};

@Injectable()
export class EtfInfoRepository extends SecuritiesBase {
  constructor(
    @Inject(DATABASE_SERVICE) service: DatabaseService,
  ) {
    super(service.getConnection(), ETF_CONFIG);
  }
}
