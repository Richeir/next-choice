import * as path from 'path';
import { DatabaseService } from '../database/database.service';
import { ConfigService } from './config.service';

const SCHEMA = path.join(__dirname, '..', '..', 'database', 'schema.sql');

describe('ConfigService', () => {
  it('默认配置来自 analysis.config.json，get 命中缓存，update 后失效', () => {
    const db = new DatabaseService({ path: ':memory:', schemaPath: SCHEMA });
    const config = new ConfigService(db);

    expect(config.get().model).toBe('gpt-4o'); // 默认文件
    expect(config.get().model).toBe('gpt-4o'); // 第二次走缓存

    const updated = config.update({ model: 'gpt-4o-mini' });
    expect(updated.model).toBe('gpt-4o-mini'); // DB 覆盖优先
    expect(config.get().model).toBe('gpt-4o-mini'); // 缓存已失效
  });

  it('DB 覆盖对未知 key 忽略；非法 JSON 保留默认值', () => {
    const db = new DatabaseService({ path: ':memory:', schemaPath: SCHEMA });
    const config = new ConfigService(db);
    const conn = db.getConnection();
    conn
      .prepare(`INSERT INTO analysis_config (key, value, updated_at) VALUES ('notAKey', '"x"', '2024-01-01T00:00:00Z')`)
      .run();
    conn
      .prepare(`INSERT INTO analysis_config (key, value, updated_at) VALUES ('maxRetries', 'not-json', '2024-01-01T00:00:00Z')`)
      .run();
    expect(config.get().maxRetries).toBe(2); // 非法 JSON 保留默认
    expect(config.get().klineLimit).toBe(120); // 未知 key 被忽略
  });
});
