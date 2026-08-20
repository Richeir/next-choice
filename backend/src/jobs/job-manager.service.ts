import { Inject, Injectable, Logger } from '@nestjs/common';
import { v4 as uuidv4 } from 'uuid';
import { DATABASE_SERVICE, DatabaseService } from '../database/database.service';
import type { SecurityType } from '../modules/kline/kline.repository';

export type JobStatus = 'pending' | 'running' | 'done' | 'failed';

export interface Job {
  id: string;
  kind: SecurityType;
  code: string;
  status: JobStatus;
  result: unknown;
  error?: string;
  createdAt: number;
  updatedAt: number;
}

/** 分析任务全局并发上限（简单信号量，防止 LLM / 分析被并发打爆）。 */
export const MAX_CONCURRENT = 3;

const ACTIVE_STATUSES: JobStatus[] = ['pending', 'running'];

interface DbJobRow {
  id: string;
  kind: string;
  code: string;
  status: string;
  result: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

/**
 * 内存 + SQLite 双写管理分析任务：
 * - per-code 去重：同一标的同一时刻只允许一个 pending/running 任务；
 * - 简单信号量限制全局并发；
 * - 任务记录落库（analysis_jobs），进程重启后可查询；中断的任务标记为 failed。
 */
@Injectable()
export class JobManagerService {
  private readonly logger = new Logger(JobManagerService.name);
  private readonly jobs = new Map<string, Job>();
  private readonly waiters: Array<() => void> = [];
  private running = 0;

  constructor(
    @Inject(DATABASE_SERVICE) private readonly db: DatabaseService,
  ) {
    this.recoverFromDb();
  }

  /** 创建任务；同标的已有 pending/running 任务时直接复用（per-code 去重）。 */
  create(kind: SecurityType, code: string): Job {
    for (const job of this.jobs.values()) {
      if (job.kind === kind && job.code === code && ACTIVE_STATUSES.includes(job.status)) {
        return job;
      }
    }
    const now = Date.now();
    const job: Job = {
      id: uuidv4(),
      kind,
      code,
      status: 'pending',
      result: null,
      createdAt: now,
      updatedAt: now,
    };
    this.jobs.set(job.id, job);
    this.insertDb(job);
    return job;
  }

  /** 查询任务：内存优先，缺失时回退 DB（重启恢复后仍可查询）。 */
  get(id: string): Job | undefined {
    return this.jobs.get(id) ?? this.selectDb(id);
  }

  update(id: string, patch: Partial<Job>): Job | undefined {
    const job = this.jobs.get(id) ?? this.selectDb(id);
    if (!job) return undefined;
    Object.assign(job, patch, { updatedAt: Date.now() });
    this.jobs.set(job.id, job);
    this.updateDb(job);
    return job;
  }

  /** 异步执行任务：并发受限（信号量），running → done / failed。 */
  async run(id: string, task: () => Promise<unknown>): Promise<void> {
    this.update(id, { status: 'running', result: null });
    await this.acquire();
    try {
      const result = await task();
      this.update(id, { status: 'done', result });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      this.update(id, { status: 'failed', error: message });
    } finally {
      this.release();
    }
  }

  /** 服务启动/实例化时从 DB 恢复任务；中断的 pending/running 置为 failed。 */
  private recoverFromDb(): void {
    for (const row of this.allDb()) {
      const job = this.rowToJob(row);
      if (job.status === 'pending' || job.status === 'running') {
        job.status = 'failed';
        job.error = 'interrupted by server restart';
        job.updatedAt = Date.now();
        this.updateDb(job);
        this.logger.warn(`Job ${job.id} (${job.kind} ${job.code}) interrupted by restart, marked failed`);
      }
      this.jobs.set(job.id, job);
    }
  }

  private acquire(): Promise<void> {
    if (this.running < MAX_CONCURRENT) {
      this.running += 1;
      return Promise.resolve();
    }
    return new Promise((resolve) => this.waiters.push(resolve));
  }

  private release(): void {
    const next = this.waiters.shift();
    if (next) next();
    else this.running -= 1;
  }

  private insertDb(job: Job): void {
    try {
      this.db
        .getConnection()
        .prepare(
          `INSERT INTO analysis_jobs (id, kind, code, status, result, error, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
        )
        .run(job.id, job.kind, job.code, job.status, serialize(job.result), job.error ?? null, iso(job.createdAt), iso(job.updatedAt));
    } catch (err) {
      this.logger.warn(`Failed to persist job ${job.id}: ${(err as Error).message}`);
    }
  }

  private updateDb(job: Job): void {
    try {
      this.db
        .getConnection()
        .prepare(
          `UPDATE analysis_jobs SET status = ?, result = ?, error = ?, updated_at = ? WHERE id = ?`,
        )
        .run(job.status, serialize(job.result), job.error ?? null, iso(job.updatedAt), job.id);
    } catch (err) {
      this.logger.warn(`Failed to update job ${job.id}: ${(err as Error).message}`);
    }
  }

  private selectDb(id: string): Job | undefined {
    try {
      const row = this.db
        .getConnection()
        .prepare('SELECT * FROM analysis_jobs WHERE id = ?')
        .get(id) as DbJobRow | undefined;
      return row ? this.rowToJob(row) : undefined;
    } catch {
      return undefined;
    }
  }

  private allDb(): DbJobRow[] {
    try {
      return this.db
        .getConnection()
        .prepare('SELECT * FROM analysis_jobs')
        .all() as DbJobRow[];
    } catch {
      return [];
    }
  }

  private rowToJob(row: DbJobRow): Job {
    return {
      id: row.id,
      kind: row.kind as SecurityType,
      code: row.code,
      status: row.status as JobStatus,
      result: deserialize(row.result),
      error: row.error ?? undefined,
      createdAt: Date.parse(row.created_at),
      updatedAt: Date.parse(row.updated_at),
    };
  }
}

function serialize(value: unknown): string | null {
  if (value === undefined || value === null) return null;
  return typeof value === 'string' ? value : JSON.stringify(value);
}

function deserialize(value: string | null): unknown {
  if (value === null || value === undefined) return null;
  try {
    return JSON.parse(value);
  } catch {
    return value;
  }
}

function iso(ts: number): string {
  return new Date(ts).toISOString();
}
