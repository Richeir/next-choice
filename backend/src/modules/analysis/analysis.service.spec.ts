import * as path from 'path';
import { NotFoundException } from '@nestjs/common';
import { AnalysisService } from './analysis.service';
import { AnalysisRepository } from './analysis.repository';
import { TechnicalAnalysisService } from './technical-analysis.service';
import { LlmService, LlmResult } from './llm.service';
import { KlineRepository, SecurityType } from '../kline/kline.repository';
import { ConfigService } from '../../config/config.service';
import { JobManagerService } from '../../jobs/job-manager.service';
import { DatabaseService } from '../../database/database.service';

/** 构造一个便于断言的技术面结果：趋势多头，dims 与 trend 可自由指定。 */
function makeTechnical(
  dims = { trend: 80, momentum: 50, valuation: 50, volume: 50, stability: 50 },
  trend: '多头' | '空头' | '震荡' = '多头',
): ReturnType<TechnicalAnalysisService['analyze']> {
  return {
    score: 0,
    signal: 'SELL',
    rating: 'D',
    isWorthBuying: 0,
    holdDays: 0,
    dims,
    ma5: null,
    ma20: null,
    ma60: null,
    trend,
    momentum20: null,
    volatility20: null,
    volumeRatio: null,
    note: '',
  };
}

function makeService() {
  const service = new AnalysisService(
    {} as never,
    new TechnicalAnalysisService() as never,
    {} as never,
    {} as never,
    {} as never,
    {} as never,
  );
  return service;
}

describe('AnalysisService.mergeLlm', () => {
  const service = makeService();

  it('LLM 存在时用 LLM 维度分合成', () => {
    const r = service.mergeLlm(makeTechnical(), {
      trend: 100,
      momentum: 100,
      valuation: 100,
      volume: 100,
      stability: 100,
      reason: '全面向好',
      llmAnalysis: '详细分析',
    });
    expect(r.score).toBe(100);
    expect(r.rating).toBe('S+');
    expect(r.signal).toBe('BUY'); // score>=65 且技术面多头
    expect(r.isWorthBuying).toBe(1);
    expect(r.holdDays).toBeGreaterThan(0);
    expect(r.llmAnalysis).toBe('详细分析');
    expect(r.dims).toEqual({ trend: 100, momentum: 100, valuation: 100, volume: 100, stability: 100 });
  });

  it('LLM 为 null 时降级用 technical.dims，score/rating/signal 与降级分一致', () => {
    const r = service.mergeLlm(makeTechnical(), null);
    // 0.25*80 + 0.2*50 + 0.2*50 + 0.15*50 + 0.2*50 = 20 + 10 + 10 + 7.5 + 10 = 57.5
    expect(r.score).toBeCloseTo(57.5);
    expect(r.rating).toBe('A'); // >=50
    expect(r.signal).toBe('HOLD'); // 45 <= 57.5 < 65
    expect(r.isWorthBuying).toBe(0);
    expect(r.holdDays).toBe(22); // 趋势多头，持有天数 = round(10 + 57.5/100*20)
    expect(r.llmAnalysis).toBeNull();
    expect(r.dims).toEqual({ trend: 80, momentum: 50, valuation: 50, volume: 50, stability: 50 }); // 降级用技术面维度分
  });

  it('LLM 高分但技术面空头时不会触发 BUY（信号方向以技术面均线为准）', () => {
    const r = service.mergeLlm(makeTechnical({ trend: 25, momentum: 50, valuation: 50, volume: 50, stability: 50 }, '空头'), {
      trend: 100,
      momentum: 100,
      valuation: 100,
      volume: 100,
      stability: 100,
      reason: 'x',
    });
    expect(r.score).toBe(100);
    expect(r.signal).toBe('HOLD'); // score>=65 但 trend !== 多头
    expect(r.isWorthBuying).toBe(0);
  });

  it('score/rating/signal 出自同一套权重与换算，口径一致', () => {
    const llmPath = service.mergeLlm(makeTechnical(), {
      trend: 70,
      momentum: 60,
      valuation: 55,
      volume: 65,
      stability: 50,
      reason: 'r',
    });
    const fallbackPath = service.mergeLlm(makeTechnical(), null);
    // 直接按 compositeScore5 权重核对 LLM 路径
    const expected = 0.25 * 70 + 0.2 * 60 + 0.2 * 55 + 0.15 * 65 + 0.2 * 50;
    expect(llmPath.score).toBeCloseTo(expected);
    // 一致性：rating/signal 都能由 score 推出
    expect(fallbackPath.rating).toBe('A');
    expect(fallbackPath.signal).toBe('HOLD');
  });
});

// ---------------------------------------------------------------------------
// execute / trigger / getJob 集成测试（内存 SQLite + 真实 schema）
// ---------------------------------------------------------------------------
const SCHEMA = path.join(__dirname, '..', '..', '..', 'database', 'schema.sql');

function makeConfig(overrides: Record<string, unknown> = {}) {
  return {
    get: () => ({
      model: 'gpt-4o',
      promptTemplate: '模板 {{securityType}} {{basicInfo}} {{klineSummary}} {{technicalIndicators}}',
      timeoutMs: 1000,
      maxRetries: 2,
      klineLimit: 120,
      temperature: 0.2,
      updatedAt: null,
      ...overrides,
    }),
  } as unknown as ConfigService;
}

/** 构造含 60 根日 K 的标的（最后交易日 2024-02-29）。
 * kind='etf' 时按采集侧现状只插入不复权（'3'）数据。 */
function setupExecuteEnv(kind: SecurityType = 'stock') {
  const db = new DatabaseService({ path: ':memory:', schemaPath: SCHEMA });
  const conn = db.getConnection();
  const code = kind === 'stock' ? '600000' : '510050';
  const infoTable = kind === 'stock' ? 'stock_info' : 'etf_info';
  conn.prepare(`INSERT INTO ${infoTable} (code, last_trade_date) VALUES (?, '2024-02-29')`).run(code);
  // ETF 采集侧仅存不复权（新浪源不支持 ETF 复权），股票两种复权都有
  const adjustflags = kind === 'stock' ? ['2', '3'] : ['3'];
  const insert = conn.prepare(
    `INSERT INTO ${kind}_kline_daily
       (date, code, open, high, low, close, preclose, volume, amount, adjustflag,
        turn, tradestatus, pctChg, isST)
     VALUES (?, ?, 10, 10, 10, ?, 10, 1000000, 0, ?, 0, '1', 0, '0')`,
  );
  const base = new Date('2024-01-01T00:00:00Z');
  for (const adjustflag of adjustflags) {
    for (let i = 0; i < 60; i++) {
      const d = new Date(base.getTime() + i * 86_400_000).toISOString().slice(0, 10);
      insert.run(d, code, 10 + i * 0.1, adjustflag);
    }
  }
  const analysisRepo = new AnalysisRepository(db);
  const klineRepo = new KlineRepository(db);
  return { db, conn, analysisRepo, klineRepo };
}

function makeExecuteService(options: { llmResult?: LlmResult | null; kind?: SecurityType } = {}) {
  const { db, conn, analysisRepo, klineRepo } = setupExecuteEnv(options.kind ?? 'stock');
  const llm = {
    analyze: jest.fn().mockResolvedValue(options.llmResult ?? null),
  } as unknown as LlmService;
  const service = new AnalysisService(
    analysisRepo,
    new TechnicalAnalysisService(),
    llm,
    klineRepo,
    {} as never,
    makeConfig(),
  );
  const execute = (service as unknown as {
    execute: (type: SecurityType, code: string) => Promise<unknown>;
  }).execute.bind(service);
  return { service, db, conn, llm, execute };
}

describe('AnalysisService.execute', () => {
  it('分析日期取最后交易日（最后一行 K 线），非 UTC 当天', async () => {
    const { execute, conn } = makeExecuteService({
      llmResult: {
        trend: 70,
        momentum: 60,
        valuation: 55,
        volume: 65,
        stability: 50,
      },
    });
    await execute('stock', '600000');
    const row = conn.prepare(`SELECT * FROM stock_analysis WHERE code = '600000'`).get() as Record<string, unknown>;
    expect(String(row.date)).toBe('2024-02-29');
  });

  it('LLM 路径落库 dims/model/prompt_version，reason 追加进 note', async () => {
    const { execute, conn } = makeExecuteService({
      llmResult: {
        trend: 70,
        momentum: 60,
        valuation: 55,
        volume: 65,
        stability: 50,
        reason: '估值合理，趋势向好',
      },
    });
    await execute('stock', '600000');
    const row = conn.prepare(`SELECT * FROM stock_analysis WHERE code = '600000'`).get() as Record<string, unknown>;
    expect(JSON.parse(row.dims as string)).toEqual({ trend: 70, momentum: 60, valuation: 55, volume: 65, stability: 50 });
    expect(row.model).toBe('gpt-4o');
    expect(String(row.prompt_version)).toMatch(/^[0-9a-f]{8}$/);
    expect(String(row.note)).toContain('趋势向好'); // reason → note
    expect(String(row.note)).toContain('综合评分'); // 技术指标摘要仍在
    expect(row.llm_analysis).toBe('估值合理，趋势向好'); // llmAnalysis 缺失时 reason 兜底进 llm_analysis
  });

  it('LLM 不可用时降级：model/prompt_version 为 null，dims 为技术面维度分', async () => {
    const { execute, conn, llm } = makeExecuteService(); // llmResult = null
    await execute('stock', '600000');
    expect(llm.analyze).toHaveBeenCalled();
    const row = conn.prepare(`SELECT * FROM stock_analysis WHERE code = '600000'`).get() as Record<string, unknown>;
    expect(row.model).toBeNull();
    expect(row.prompt_version).toBeNull();
    const dims = JSON.parse(row.dims as string) as Record<string, number>;
    expect(dims).toHaveProperty('trend');
    expect(dims).toHaveProperty('stability');
    expect(row.note).toBeTruthy();
  });

  it('ETF 用不复权（adjustflag=3）K 线：仅有不复权数据也能分析成功', async () => {
    const { execute, conn } = makeExecuteService({ kind: 'etf' });
    await execute('etf', '510050');
    const row = conn.prepare(`SELECT * FROM etf_analysis WHERE code = '510050'`).get() as Record<string, unknown>;
    expect(String(row.date)).toBe('2024-02-29');
    expect(row.score).not.toBeNull();
  });
});

describe('AnalysisService.trigger / getJob', () => {
  it('trigger 对同一标的中途去重；getJob 返回任务状态', async () => {
    const { db, analysisRepo, klineRepo } = setupExecuteEnv();
    const llm = {
      analyze: jest.fn().mockImplementation(async () => {
        await new Promise((r) => setTimeout(r, 20));
        return {
          trend: 70,
          momentum: 60,
          valuation: 55,
          volume: 65,
          stability: 50,
          reason: 'ok',
        };
      }),
    } as unknown as LlmService;
    const jobs = new JobManagerService(db);
    const service = new AnalysisService(
      analysisRepo,
      new TechnicalAnalysisService(),
      llm,
      klineRepo,
      jobs,
      makeConfig(),
    );
    const r1 = service.trigger('stock', '600000');
    const r2 = service.trigger('stock', '600000');
    expect(r2.jobId).toBe(r1.jobId); // per-code 去重

    // 等待任务完成（轮询 DB 状态）
    const deadline = Date.now() + 2000;
    for (;;) {
      const row = db
        .getConnection()
        .prepare(`SELECT status FROM analysis_jobs WHERE id = ?`)
        .get(r1.jobId) as { status: string };
      if (row.status === 'done' || row.status === 'failed') break;
      if (Date.now() > deadline) throw new Error('job timeout');
      await new Promise((r) => setTimeout(r, 10));
    }
    expect(llm.analyze).toHaveBeenCalledTimes(1); // 去重后只执行一次
    expect(service.getJob(r1.jobId).status).toBe('done');
  });

  it('getJob 对未知 id 抛 NotFoundException（而非假 failed）', () => {
    const service = new AnalysisService(
      {} as never,
      {} as never,
      {} as never,
      {} as never,
      { get: () => undefined } as never,
      {} as never,
    );
    expect(() => service.getJob('no-such-job')).toThrow(NotFoundException);
  });
});
