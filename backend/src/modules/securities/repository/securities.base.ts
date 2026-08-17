import Database from 'better-sqlite3';

export interface ListOptions {
  page: number;
  pageSize: number;
  order: 'asc' | 'desc';
  /** 排序字段（白名单内）。 */
  sortBy?: string;
  keyword?: string;
  market?: string;
  industry?: string;
  category?: string;
  manager?: string;
  status?: string;
}

export interface Paginated<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
}

export interface InfoTableConfig {
  /** 基础信息表名。 */
  infoTable: string;
  /** 分析表名。 */
  analysisTable: string;
  /** 列表要返回的基础信息列。 */
  listColumns: string[];
  /** 详情要返回的基础信息列。 */
  detailColumns: string[];
  /** 允许排序的字段名 → SQL 表达式。 */
  sortFields: Record<string, string>;
  /** 评级排序的 CASE 表达式（对 a.rating 求档位值）。 */
  ratingOrder: string;
  /** 可供过滤的基础信息列（keyword 之外）。 */
  filterFields: string[];
}

interface WhereResult {
  sql: string;
  params: unknown[];
}

/** 证券列表/详情/分析历史的通用 Repository 基类（股票与 ETF 复用）。 */
export abstract class SecuritiesBase {
  constructor(
    protected readonly db: Database.Database,
    protected readonly cfg: InfoTableConfig,
  ) {}

  list(opts: ListOptions): Paginated<Record<string, unknown>> {
    const where = this.buildWhere(opts);

    const totalRow = this.db
      .prepare(`SELECT COUNT(*) AS total FROM ${this.cfg.infoTable} si ${where.sql}`)
      .get(...where.params) as { total: number };

    const orderSql = this.buildOrder(opts.sortBy, opts.order);
    const listCols = this.cfg.listColumns.join(', ');
    const offset = (opts.page - 1) * opts.pageSize;

    const rows = this.db
      .prepare(
        `SELECT si.${listCols},
                a.rating AS rating, a.score AS score, a.signal AS signal,
                a.date AS analysis_date
         FROM ${this.cfg.infoTable} si
         LEFT JOIN (
           SELECT code, rating, score, signal, date,
                  ROW_NUMBER() OVER (PARTITION BY code ORDER BY date DESC) AS rn
           FROM ${this.cfg.analysisTable}
         ) a ON a.code = si.code AND a.rn = 1
         ${where.sql}
         ORDER BY ${orderSql}
         LIMIT ? OFFSET ?`,
      )
      .all(...where.params, opts.pageSize, offset) as Record<string, unknown>[];

    return { items: rows, total: totalRow.total, page: opts.page, pageSize: opts.pageSize };
  }

  findDetail(code: string): Record<string, unknown> | undefined {
    const cols = this.cfg.detailColumns.join(', ');
    return this.db
      .prepare(`SELECT ${cols} FROM ${this.cfg.infoTable} si WHERE si.code = ?`)
      .get(code) as Record<string, unknown> | undefined;
  }

  listAnalysis(
    code: string,
    page: number,
    pageSize: number,
  ): Paginated<Record<string, unknown>> {
    const totalRow = this.db
      .prepare(`SELECT COUNT(*) AS total FROM ${this.cfg.analysisTable} WHERE code = ?`)
      .get(code) as { total: number };
    const offset = (page - 1) * pageSize;
    const rows = this.db
      .prepare(
        `SELECT * FROM ${this.cfg.analysisTable}
         WHERE code = ? ORDER BY date DESC LIMIT ? OFFSET ?`,
      )
      .all(code, pageSize, offset) as Record<string, unknown>[];
    return { items: rows, total: totalRow.total, page, pageSize };
  }

  findLatestAnalysis(code: string): Record<string, unknown> | undefined {
    return this.db
      .prepare(
        `SELECT * FROM ${this.cfg.analysisTable}
         WHERE code = ? ORDER BY date DESC LIMIT 1`,
      )
      .get(code) as Record<string, unknown> | undefined;
  }

  private buildWhere(opts: ListOptions): WhereResult {
    const clauses: string[] = [];
    const params: unknown[] = [];
    if (opts.keyword) {
      clauses.push(`(si.code LIKE ? OR si.code_name LIKE ?)`);
      const kw = `%${opts.keyword}%`;
      params.push(kw, kw);
    }
    if (opts.market) {
      clauses.push(`si.market = ?`);
      params.push(opts.market);
    }
    if (opts.status) {
      clauses.push(`si.status = ?`);
      params.push(opts.status);
    }
    for (const field of this.cfg.filterFields) {
      const val = (opts as unknown as Record<string, unknown>)[field];
      if (val) {
        clauses.push(`si.${field} = ?`);
        params.push(val);
      }
    }
    return { sql: clauses.length ? `WHERE ${clauses.join(' AND ')}` : '', params };
  }

  private buildOrder(sortBy: string | undefined, order: 'asc' | 'desc'): string {
    const dir = order === 'asc' ? 'ASC' : 'DESC';
    if (sortBy === 'rating') {
      return `CASE a.rating ${this.cfg.ratingOrder} END ${dir}`;
    }
    const col = sortBy ? this.cfg.sortFields[sortBy] : undefined;
    if (col) {
      return `${col} ${dir}`;
    }
    return `si.code ASC`;
  }
}
