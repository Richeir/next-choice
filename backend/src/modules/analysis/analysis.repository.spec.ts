import * as path from 'path';
import { DatabaseService } from '../../database/database.service';
import { AnalysisRepository, AnalysisInsert } from './analysis.repository';

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
