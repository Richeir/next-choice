import { Inject, Injectable } from '@nestjs/common';
import { DatabaseService } from '../database/database.service';

export interface AnalysisConfig {
  model: string;
  promptTemplate: string;
  timeoutMs: number;
  maxRetries: number;
  klineLimit: number;
  temperature: number;
  /** 最近一次配置更新时间（来自 DB 覆盖）。 */
  updatedAt?: string | null;
}

const CONFIG_KEYS: (keyof AnalysisConfig)[] = [
  'model',
  'promptTemplate',
  'timeoutMs',
  'maxRetries',
  'klineLimit',
  'temperature',
];

@Injectable()
export class ConfigService {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  private readonly defaults: AnalysisConfig = require('./analysis.config.json');

  constructor(
    @Inject('DATABASE_SERVICE') private readonly db: DatabaseService,
  ) {}

  /** 返回合并后的配置：DB 覆盖优先于默认文件。 */
  get(): AnalysisConfig {
    const merged: AnalysisConfig = { ...this.defaults };
    let rows: { key: string; value: string }[] = [];
    try {
      rows = this.db
        .getConnection()
        .prepare('SELECT key, value FROM analysis_config')
        .all() as { key: string; value: string }[];
    } catch {
      // analysis_config 表可能尚未建立，忽略并使用默认值
      rows = [];
    }
    for (const row of rows) {
      if (!CONFIG_KEYS.includes(row.key as keyof AnalysisConfig)) continue;
      try {
        (merged as unknown as Record<string, unknown>)[row.key] = JSON.parse(row.value);
      } catch {
        // 无法解析则保留默认值
      }
    }
    const latest = dbRowForUpdatedAt(this.db);
    merged.updatedAt = latest ?? null;
    return merged;
  }

  /** 覆盖配置：写满 key 即 UPDATE，否则 INSERT。 */
  update(patch: Partial<AnalysisConfig>): AnalysisConfig {
    const db = this.db.getConnection();
    const upsert = db.prepare(
      `INSERT INTO analysis_config (key, value, updated_at) VALUES (?, ?, ?)
       ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at`,
    );
    const now = new Date().toISOString();
    for (const key of CONFIG_KEYS) {
      if (patch[key] !== undefined) {
        upsert.run(key, JSON.stringify(patch[key]), now);
      }
    }
    return this.get();
  }
}

function dbRowForUpdatedAt(db: DatabaseService): string | null {
  try {
    const row = db
      .getConnection()
      .prepare('SELECT MAX(updated_at) AS ts FROM analysis_config')
      .get() as { ts: string | null } | undefined;
    return row?.ts ?? null;
  } catch {
    return null;
  }
}
