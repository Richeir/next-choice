import { Injectable, Logger, OnApplicationShutdown } from '@nestjs/common';
import Database from 'better-sqlite3';

/** 通过依赖注入令牌访问 DatabaseService，避免模块间循环依赖。 */
export const DATABASE_SERVICE = 'DATABASE_SERVICE';

export interface DbOptions {
  /** SQLite 文件路径。 */
  path: string;
  /** 建表 SQL 文件路径（不存在则跳过，假定表已存在）。 */
  schemaPath?: string;
}

@Injectable()
export class DatabaseService implements OnApplicationShutdown {
  private readonly logger = new Logger(DatabaseService.name);
  private db: Database.Database;

  constructor(options: DbOptions) {
    this.connect(options);
  }

  private connect(options: DbOptions): void {
    this.db = new Database(options.path);
    this.db.pragma('journal_mode = WAL');
    this.db.pragma('foreign_keys = ON');
    if (options.schemaPath) {
      this.applySchema(options.schemaPath);
    }
    this.migrate();
    this.logger.log(`Connected to SQLite at ${options.path}`);
  }

  private applySchema(schemaPath: string): void {
    const fs = require('fs');
    if (!fs.existsSync(schemaPath)) {
      this.logger.warn(`Schema file not found, skipping: ${schemaPath}`);
      return;
    }
    const sql = fs.readFileSync(schemaPath, 'utf8');
    this.db.exec(sql);
  }

  /**
   * 轻量迁移：为旧库补齐新增列（schema.sql 的 CREATE TABLE IF NOT EXISTS
   * 不会改动已存在的表，这里逐列检查并 ALTER TABLE ADD COLUMN）。
   */
  private migrate(): void {
    const adds: Array<[string, string, string]> = [
      ['stock_analysis', 'dims', 'TEXT'],
      ['stock_analysis', 'model', 'TEXT'],
      ['stock_analysis', 'prompt_version', 'TEXT'],
      ['etf_analysis', 'dims', 'TEXT'],
      ['etf_analysis', 'model', 'TEXT'],
      ['etf_analysis', 'prompt_version', 'TEXT'],
    ];
    for (const [table, column, ddl] of adds) {
      try {
        const row = this.db
          .prepare('SELECT COUNT(*) AS n FROM pragma_table_info(?) WHERE name = ?')
          .get(table, column) as { n: number };
        if (row.n === 0) {
          this.db.exec(`ALTER TABLE ${table} ADD COLUMN ${column} ${ddl}`);
          this.logger.log(`Schema migrated: ${table}.${column} added`);
        }
      } catch (err) {
        // 表可能尚未建立（如全新库缺表），跳过即可
        this.logger.warn(
          `Schema migration skipped for ${table}.${column}: ${(err as Error).message}`,
        );
      }
    }
  }

  /** 暴露底层连接供 Repository 使用。 */
  getConnection(): Database.Database {
    return this.db;
  }

  onApplicationShutdown(): void {
    if (this.db) {
      this.db.close();
      this.logger.log('SQLite connection closed');
    }
  }
}

/** 构造默认数据库路径：默认指向仓库根的 data/market.db，可用 DB_PATH 覆盖。 */
export function resolveDbPath(env = process.env): string {
  return env.DB_PATH || require('path').join(__dirname, '..', '..', '..', 'data', 'market.db');
}
