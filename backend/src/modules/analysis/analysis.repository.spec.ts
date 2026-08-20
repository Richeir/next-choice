import * as path from 'path';
import { DatabaseService } from '../../database/database.service';
import { AnalysisRepository, AnalysisInsert, isValidBackfillValue } from './analysis.repository';

const SCHEMA = path.join(__dirname, '..', '..', '..', 'database', 'schema.sql');

function setup() {
  const db = new DatabaseService({ path: ':memory:', schemaPath: SCHEMA });
  const repo = new AnalysisRepository(db);
  return { db, repo };
}

function makeInsert(overrides: Partial<AnalysisInsert> = {}): AnalysisInsert {
  return {
    date: '2024-03-29',
    score: 80,
    signal: 'BUY',
    rating: 'S',
    isWorthBuying: 1,
    holdDays: 20,
    ma5: 10,
    ma20: 9,
    ma60: 8,
    trend: '多头',
    momentum20: 10,
    volatility20: 30,
    volumeRatio: 1.5,
    note: '趋势：多头',
    llmAnalysis: null,
    dims: '{"trend":80,"momentum":70,"valuation":50,"volume":60,"stability":70}',
    model: 'gpt-4o',
    promptVersion: 'abc12345',
    ...overrides,
  };
}

describe('isValidBackfillValue', () => {
  it('字符串须非空且不超长', () => {
    expect(isValidBackfillValue('industry', '银行')).toBe(true);
    expect(isValidBackfillValue('industry', '')).toBe(false);
    expect(isValidBackfillValue('industry', '  ')).toBe(false);
    expect(isValidBackfillValue('industry', 'x'.repeat(101))).toBe(false);
    expect(isValidBackfillValue('fullName', 'x'.repeat(200))).toBe(true);
  });

  it('数值须有限；52 周高低须为正，其余非负', () => {
    expect(isValidBackfillValue('pb', 1.2)).toBe(true);
    expect(isValidBackfillValue('pb', -1)).toBe(false);
    expect(isValidBackfillValue('pb', NaN)).toBe(false);
    expect(isValidBackfillValue('pb', Infinity)).toBe(false);
    expect(isValidBackfillValue('high52w', 10)).toBe(true);
    expect(isValidBackfillValue('high52w', 0)).toBe(false);
    expect(isValidBackfillValue('low52w', 0.5)).toBe(true);
  });

  it('非字符串/数值一律拒绝', () => {
    expect(isValidBackfillValue('industry', 123)).toBe(false);
    expect(isValidBackfillValue('pb', '1.2')).toBe(false);
    expect(isValidBackfillValue('pb', null)).toBe(false);
  });
});

describe('AnalysisRepository.backfillInfo', () => {
  it('仅回填空字段：已有值不被 LLM 覆盖，并记录 llm_backfill_at', () => {
    const { db, repo } = setup();
    const conn = db.getConnection();
    conn
      .prepare(`INSERT INTO stock_info (code, industry, pb) VALUES ('sh.600000', '银行', 1.2)`)
      .run();
    repo.backfillInfo('stock', 'sh.600000', {
      trend: 70,
      momentum: 60,
      valuation: 55,
      volume: 65,
      stability: 50,
      industry: '白酒', // 已有值，忽略
      lastAmount: 9.9e8, // 空，回填
      pb: 3.5, // 已有值，忽略
      fullName: '某某股份有限公司', // 空，回填
    });
    const row = conn
      .prepare(`SELECT * FROM stock_info WHERE code = 'sh.600000'`)
      .get() as Record<string, unknown>;
    expect(row.industry).toBe('银行');
    expect(row.pb).toBe(1.2);
    expect(row.last_amount).toBe(9.9e8);
    expect(row.full_name).toBe('某某股份有限公司');
    expect(row.llm_backfill_at).toBeTruthy();
  });

  it('全部值已被占用或校验不过时只更新时间戳（或直接跳过）', () => {
    const { db, repo } = setup();
    const conn = db.getConnection();
    conn.prepare(`INSERT INTO stock_info (code, industry) VALUES ('sh.600001', '银行')`).run();
    repo.backfillInfo('stock', 'sh.600001', {
      trend: 70,
      momentum: 60,
      valuation: 55,
      volume: 65,
      stability: 50,
      industry: '白酒', // 已有值
    });
    const row = conn
      .prepare(`SELECT * FROM stock_info WHERE code = 'sh.600001'`)
      .get() as Record<string, unknown>;
    expect(row.industry).toBe('银行');
    expect(row.llm_backfill_at).toBeNull(); // 无有效回填，不更新时间戳
  });

  it('非法值（负数市值/超长行业/非有限数）不落库，合法字段正常回填', () => {
    const { db, repo } = setup();
    const conn = db.getConnection();
    conn.prepare(`INSERT INTO stock_info (code) VALUES ('sh.600002')`).run();
    repo.backfillInfo('stock', 'sh.600002', {
      trend: 70,
      momentum: 60,
      valuation: 55,
      volume: 65,
      stability: 50,
      industry: 'x'.repeat(101), // 超长，丢弃
      pb: -2, // 负数，丢弃
      high52w: 0, // 52 周高须为正，丢弃
      fullName: '合法全称', // 有效，回填
      lastAmount: Number.POSITIVE_INFINITY, // 非有限，丢弃
    });
    const row = conn
      .prepare(`SELECT * FROM stock_info WHERE code = 'sh.600002'`)
      .get() as Record<string, unknown>;
    expect(row.industry).toBeNull();
    expect(row.pb).toBeNull();
    expect(row.high_52w).toBeNull();
    expect(row.last_amount).toBeNull();
    expect(row.full_name).toBe('合法全称');
    expect(row.llm_backfill_at).toBeTruthy();
  });
});

describe('AnalysisRepository.insertAnalysis', () => {
  it('写入分析新列（dims/model/prompt_version）并可重复 UPSERT', () => {
    const { db, repo } = setup();
    repo.insertAnalysis('stock', 'sh.600000', makeInsert());
    repo.insertAnalysis('stock', 'sh.600000', makeInsert({ score: 90, rating: 'S+' }));

    const conn = db.getConnection();
    const rows = conn
      .prepare(`SELECT * FROM stock_analysis WHERE code = 'sh.600000'`)
      .all() as Record<string, unknown>[];
    expect(rows).toHaveLength(1); // ON CONFLICT 更新而非新增
    expect(rows[0].score).toBe(90);
    expect(rows[0].rating).toBe('S+');
    expect(rows[0].dims).toBe(makeInsert().dims);
    expect(rows[0].model).toBe('gpt-4o');
    expect(rows[0].prompt_version).toBe('abc12345');
  });
});
