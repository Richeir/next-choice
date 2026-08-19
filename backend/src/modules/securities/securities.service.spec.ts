import Database from 'better-sqlite3';
import { SecuritiesService } from './securities.service';
import { StockInfoRepository } from './repository/stock-info.repository';
import { EtfInfoRepository } from './repository/etf-info.repository';

describe('SecuritiesService 详情行情', () => {
  let db: Database.Database;
  let service: SecuritiesService;

  const STOCK_INFO_COLS =
    'code, code_name, market, type, ipoDate, outDate, status, industry, ' +
    'last_trade_date, last_close, last_pct_chg, last_amount, pe_ttm, pb, ' +
    'full_name, total_market_cap, high_52w, low_52w, last_fetch_date';

  beforeEach(() => {
    db = new Database(':memory:');
    // stock_info + 不复权日 K（与 backend/database/schema.sql 一致的最小建表）
    db.exec(`CREATE TABLE stock_info (
      ${STOCK_INFO_COLS}
    );`);
    db.exec(`CREATE TABLE stock_kline_daily (
      date TEXT NOT NULL, code TEXT NOT NULL, open REAL, high REAL, low REAL,
      close REAL, preclose REAL, volume REAL, amount REAL,
      adjustflag TEXT NOT NULL, turn REAL, tradestatus TEXT, pctChg REAL, isST TEXT,
      PRIMARY KEY (code, date, adjustflag)
    );`);
    db.exec(`CREATE TABLE etf_info (
      code TEXT, code_name TEXT, market TEXT, type TEXT, ipoDate TEXT,
      outDate TEXT, status TEXT, category TEXT, manager TEXT,
      last_trade_date TEXT, last_close REAL, last_pct_chg REAL,
      fund_scale REAL, last_fetch_date TEXT
    );`);
    db.exec(`CREATE TABLE etf_kline_daily (
      date TEXT NOT NULL, code TEXT NOT NULL, open REAL, high REAL, low REAL,
      close REAL, preclose REAL, volume REAL, amount REAL,
      adjustflag TEXT NOT NULL, turn REAL, tradestatus TEXT, pctChg REAL, isST TEXT,
      PRIMARY KEY (code, date, adjustflag)
    );`);

    const fakeService = { getConnection: () => db };
    service = new SecuritiesService(
      new StockInfoRepository(fakeService as never),
      new EtfInfoRepository(fakeService as never),
    );
  });

  afterEach(() => db.close());

  it('快照过期时详情返回 K 线最后一个交易日收盘价', async () => {
    // 快照停留在 2026-08-18，但 K 线已更新到 2026-08-19
    db.prepare(
      `INSERT INTO stock_info (${STOCK_INFO_COLS})
       VALUES ('sh.600000','浦发银行','SH','1','1999-11-10','','1','银行',
               '2026-08-18', 8.97, -0.7743, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL)`,
    ).run();
    db.prepare(
      `INSERT INTO stock_kline_daily
       (date, code, open, high, low, close, preclose, volume, amount,
        adjustflag, turn, tradestatus, pctChg, isST)
       VALUES ('2026-08-18','sh.600000',9.0,9.1,8.9,8.97,9.04,1000,1000,'3',0.5,'1',-0.7743,'0')`,
    ).run();
    db.prepare(
      `INSERT INTO stock_kline_daily
       (date, code, open, high, low, close, preclose, volume, amount,
        adjustflag, turn, tradestatus, pctChg, isST)
       VALUES ('2026-08-19','sh.600000',9.0,9.2,8.95,9.08,8.97,1200,1200,'3',0.6,'1',1.226,'0')`,
    ).run();

    const detail = (await service.getStockDetail('sh.600000')) as Record<string, unknown>;
    expect(detail.lastTradeDate).toBe('2026-08-19');
    expect(detail.lastClose).toBe(9.08);
    expect(detail.lastPctChg).toBe(1.226);
  });

  it('无 K 线数据时回退到快照值', async () => {
    db.prepare(
      `INSERT INTO stock_info (${STOCK_INFO_COLS})
       VALUES ('sh.600000','浦发银行','SH','1','1999-11-10','','1','银行',
               '2026-08-18', 8.97, -0.7743, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL)`,
    ).run();

    const detail = (await service.getStockDetail('sh.600000')) as Record<string, unknown>;
    expect(detail.lastTradeDate).toBe('2026-08-18');
    expect(detail.lastClose).toBe(8.97);
  });
});
