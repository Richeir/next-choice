import { Test } from '@nestjs/testing';
import { INestApplication, ValidationPipe } from '@nestjs/common';
import request from 'supertest';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { AppModule } from '../src/app.module';
import Database from 'better-sqlite3';

/** 生成一段升序 K 线数据。 */
function genKlines(code: string, days: number, base = 10): Array<Record<string, unknown>> {
  const rows: Array<Record<string, unknown>> = [];
  const start = new Date('2023-11-01T00:00:00Z');
  let close = base;
  for (let i = 0; i < days; i++) {
    const d = new Date(start);
    d.setUTCDate(start.getUTCDate() + i * 1);
    const date = d.toISOString().slice(0, 10);
    close = base + i * 0.05;
    rows.push({
      date,
      code,
      open: close - 0.1,
      high: close + 0.2,
      low: close - 0.2,
      close,
      volume: 1_000_000 + i * 1000,
      amount: close * 1_000_000,
      adjustflag: '2',
      pctChg: i === 0 ? 0 : 0.5,
    });
  }
  return rows;
}

describe('Backend e2e (Issue #6)', () => {
  let app: INestApplication;
  let db: Database.Database;
  let dbPath: string;

  beforeAll(async () => {
    // 用临时 SQLite 文件，避免污染真实数据
    dbPath = path.join(os.tmpdir(), `next-choice-e2e-${Date.now()}.db`);
    const schema = fs.readFileSync(
      path.join(__dirname, '..', 'database', 'schema.sql'),
      'utf8',
    );
    const seed = new Database(dbPath);
    seed.exec(schema);
    // 种子数据
    seed
      .prepare(
        `INSERT INTO stock_info (code, code_name, market, type, ipoDate, status, last_trade_date, last_close, last_pct_chg, pe_ttm) VALUES (?,?,?,?,?,?,?,?,?,?)`,
      )
      .run('sh.600000', '浦发银行', 'SH', '1', '1999-11-10', '1', '2024-01-31', 6.83, 0.0, 5.2);
    seed
      .prepare(
        `INSERT INTO stock_info (code, code_name, market, type, ipoDate, status, last_trade_date, last_close, last_pct_chg, pe_ttm) VALUES (?,?,?,?,?,?,?,?,?,?)`,
      )
      .run('sz.000001', '平安银行', 'SZ', '1', '1991-04-03', '1', '2024-01-31', 10.5, 0.1, 7.1);
    seed
      .prepare(
        `INSERT INTO etf_info (code, code_name, market, type, ipoDate, status, last_trade_date, last_close, last_pct_chg) VALUES (?,?,?,?,?,?,?,?,?)`,
      )
      .run('sh.510010', '沪深300ETF', 'SH', '5', '2020-01-01', '1', '2024-01-31', 4.182, 0.04);

    const ins = seed.prepare(
      `INSERT INTO stock_kline_daily (date, code, open, high, low, close, volume, amount, adjustflag, pctChg) VALUES (@date,@code,@open,@high,@low,@close,@volume,@amount,@adjustflag,@pctChg)`,
    );
    for (const k of genKlines('sh.600000', 80)) {
      ins.run(k);
    }
    const eIns = seed.prepare(
      `INSERT INTO etf_kline_daily (date, code, open, high, low, close, volume, amount, adjustflag, pctChg) VALUES (@date,@code,@open,@high,@low,@close,@volume,@amount,@adjustflag,@pctChg)`,
    );
    for (const k of genKlines('sh.510010', 80, 4)) {
      eIns.run(k);
    }

    // 分析记录：用于评级排序与详情
    seed
      .prepare(
        `INSERT INTO stock_analysis (code, date, score, signal, rating, is_worth_buying, hold_days, note) VALUES (?,?,?,?,?,?,?,?)`,
      )
      .run('sh.600000', '2024-01-06', 72, 'BUY', 'A+', 1, 15, '测试');
    seed
      .prepare(
        `INSERT INTO stock_analysis (code, date, score, signal, rating, is_worth_buying, hold_days, note) VALUES (?,?,?,?,?,?,?,?)`,
      )
      .run('sz.000001', '2024-01-06', 45, 'HOLD', 'B+', 0, 0, '测试2');
    seed.close();

    process.env.DB_PATH = dbPath;
    const moduleRef = await Test.createTestingModule({ imports: [AppModule] }).compile();
    app = moduleRef.createNestApplication();
    app.setGlobalPrefix('api');
    app.useGlobalPipes(
      new ValidationPipe({ transform: true, whitelist: true, forbidNonWhitelisted: false }),
    );
    await app.init();
    db = new Database(dbPath);
  });

  afterAll(async () => {
    await app.close();
    db.close();
    try {
      fs.unlinkSync(dbPath);
    } catch {
      /* ignore */
    }
  });

  it('GET /api/stats 返回首页统计', async () => {
    const res = await request(app.getHttpServer()).get('/api/stats').expect(200);
    expect(res.body.stockCnt).toBe(2);
    expect(res.body.etfCnt).toBe(1);
    expect(res.body.analyzedCnt).toBe(2);
    // 两条分析都属于股票，ETF 没有：合计值不能用来算 ETF 覆盖率
    expect(res.body.stockAnalyzedCnt).toBe(2);
    expect(res.body.etfAnalyzedCnt).toBe(0);
    expect(res.body.analyzedTimes).toBe(2);
    expect(res.body.lastTradeDate).toBe('2024-01-31');
  });

  it('GET /api/stocks 返回分页列表与最新分析摘要', async () => {
    const res = await request(app.getHttpServer()).get('/api/stocks?pageSize=10').expect(200);
    expect(res.body.total).toBe(2);
    expect(res.body.page).toBe(1);
    expect(res.body.items).toHaveLength(2);
    const item = res.body.items.find((x: any) => x.code === 'sh.600000');
    expect(item.codeName).toBe('浦发银行');
    expect(item.lastTradeDate).toBe('2024-01-31');
    expect(item.analysis).toMatchObject({ rating: 'A+', score: 72, signal: 'BUY' });
  });

  it('GET /api/stocks?keyword= 模糊查询', async () => {
    const res = await request(app.getHttpServer()).get('/api/stocks?keyword=浦发').expect(200);
    expect(res.body.total).toBe(1);
    expect(res.body.items[0].code).toBe('sh.600000');
  });

  it('GET /api/stocks?sortBy=rating 按评级排序', async () => {
    const res = await request(app.getHttpServer()).get('/api/stocks?sortBy=rating&order=desc').expect(200);
    expect(res.body.items[0].code).toBe('sh.600000'); // A+ 高于 B+
  });

  it('GET /api/stocks?market=SH 过滤', async () => {
    const res = await request(app.getHttpServer()).get('/api/stocks?market=SH').expect(200);
    expect(res.body.total).toBe(1);
    expect(res.body.items[0].code).toBe('sh.600000');
  });

  it('GET /api/stocks?analysisStatus= 按分析状态过滤，total 与结果一致', async () => {
    const analyzed = await request(app.getHttpServer())
      .get('/api/stocks?analysisStatus=analyzed')
      .expect(200);
    expect(analyzed.body.total).toBe(2);
    expect(analyzed.body.items).toHaveLength(2);

    const pending = await request(app.getHttpServer())
      .get('/api/stocks?analysisStatus=pending')
      .expect(200);
    expect(pending.body.total).toBe(0);
    expect(pending.body.items).toHaveLength(0);

    // ETF 没有分析记录，pending 应命中唯一一只
    const etfPending = await request(app.getHttpServer())
      .get('/api/etfs?analysisStatus=pending')
      .expect(200);
    expect(etfPending.body.total).toBe(1);
    expect(etfPending.body.items[0].code).toBe('sh.510010');
  });

  it('GET /api/stocks?analysisStatus=bogus 非法值返回 400', async () => {
    await request(app.getHttpServer()).get('/api/stocks?analysisStatus=bogus').expect(400);
  });

  it('GET /api/stocks/sh.600000 返回详情', async () => {
    const res = await request(app.getHttpServer()).get('/api/stocks/sh.600000').expect(200);
    expect(res.body.codeName).toBe('浦发银行');
    expect(res.body.lastClose).toBe(6.83);
  });

  it('GET /api/stocks/zz.999999 不存在返回 404', async () => {
    await request(app.getHttpServer()).get('/api/stocks/zz.999999').expect(404);
  });

  it('GET /api/stocks/sh.600000/analysis 返回分析历史', async () => {
    const res = await request(app.getHttpServer()).get('/api/stocks/sh.600000/analysis').expect(200);
    expect(res.body.total).toBe(1);
    expect(res.body.items[0]).toMatchObject({ score: 72, rating: 'A+', signal: 'BUY' });
  });

  it('GET /api/etfs 返回 ETF 列表且 nav=lastClose', async () => {
    const res = await request(app.getHttpServer()).get('/api/etfs').expect(200);
    expect(res.body.total).toBe(1);
    const item = res.body.items[0];
    expect(item.code).toBe('sh.510010');
    expect(item.nav).toBe(4.182);
  });

  it('GET /api/etfs/sh.510010 返回详情', async () => {
    const res = await request(app.getHttpServer()).get('/api/etfs/sh.510010').expect(200);
    expect(res.body.nav).toBe(4.182);
  });

  it('GET /api/stocks/sh.600000/kline 返回 K 线', async () => {
    const res = await request(app.getHttpServer()).get('/api/stocks/sh.600000/kline').expect(200);
    expect(res.body.items.length).toBeGreaterThan(0);
    expect(res.body.items[0]).toHaveProperty('close');
    expect(res.body.items[0].date).toBe('2023-11-01');
  });

  it('GET /api/stocks/sh.600000/kline?limit=5 限制条数', async () => {
    const res = await request(app.getHttpServer())
      .get('/api/stocks/sh.600000/kline?limit=5')
      .expect(200);
    expect(res.body.items).toHaveLength(5);
  });

  it('GET /api/stocks/sh.600000/kline?frequency=weekly 非法频率返回 400', async () => {
    await request(app.getHttpServer()).get('/api/stocks/sh.600000/kline?frequency=nope').expect(400);
  });

  it('POST /api/stocks/sh.600000/analyze 触发异步分析', async () => {
    const res = await request(app.getHttpServer())
      .post('/api/stocks/sh.600000/analyze')
      .expect(201);
    expect(res.body.accepted).toBe(true);
    expect(res.body.jobId).toBeDefined();
    // 轮询任务状态直至 done
    let status = 'pending';
    let attempts = 0;
    while (status !== 'done' && attempts < 20) {
      await new Promise((r) => setTimeout(r, 50));
      const job = await request(app.getHttpServer())
        .get(`/api/jobs/${res.body.jobId}`)
        .expect(200);
      status = job.body.status;
      attempts++;
    }
    expect(status).toBe('done');
    // 分析应已写入
    const analysis = await request(app.getHttpServer())
      .get('/api/stocks/sh.600000/analysis')
      .expect(200);
    expect(analysis.body.total).toBeGreaterThanOrEqual(2);
    expect(analysis.body.items[0].score).toBeGreaterThan(0);
  });

  it('GET /api/jobs/nonexistent 返回 404（而非假 failed 状态）', async () => {
    await request(app.getHttpServer()).get('/api/jobs/nope').expect(404);
  });

  it('POST /api/stocks/zz.999999/analyze 不存在返回 404', async () => {
    await request(app.getHttpServer()).post('/api/stocks/zz.999999/analyze').expect(404);
  });

  it('GET /api/config/analysis 返回默认配置', async () => {
    const res = await request(app.getHttpServer()).get('/api/config/analysis').expect(200);
    expect(res.body.model).toBe('gpt-4o');
    expect(res.body.promptTemplate).toContain('{{code}}'.slice(0, 2)); // 有模板
  });

  it('PUT /api/config/analysis 更新配置', async () => {
    const res = await request(app.getHttpServer())
      .put('/api/config/analysis')
      .send({ model: 'deepseek-chat' })
      .expect(200);
    expect(res.body.model).toBe('deepseek-chat');
    const again = await request(app.getHttpServer()).get('/api/config/analysis').expect(200);
    expect(again.body.model).toBe('deepseek-chat');
  });
});
