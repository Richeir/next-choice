import { DatabaseService } from '../database/database.service';
import { JobManagerService, MAX_CONCURRENT } from './job-manager.service';

function createDb(): DatabaseService {
  const db = new DatabaseService({ path: ':memory:' });
  db.getConnection().exec(`
    CREATE TABLE analysis_jobs (
      id         TEXT PRIMARY KEY,
      kind       TEXT NOT NULL,
      code       TEXT NOT NULL,
      status     TEXT NOT NULL,
      result     TEXT,
      error      TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
  `);
  return db;
}

function waitFor(assert: () => void, timeoutMs = 2000): Promise<void> {
  const start = Date.now();
  return new Promise((resolve, reject) => {
    const tick = () => {
      try {
        assert();
        resolve();
      } catch {
        if (Date.now() - start > timeoutMs) reject(new Error('waitFor timeout'));
        else setTimeout(tick, 10);
      }
    };
    tick();
  });
}

describe('JobManagerService', () => {
  it('同一标的进行中任务去重，done 后可重新创建', () => {
    const db = createDb();
    const service = new JobManagerService(db);
    const j1 = service.create('stock', '600000');
    expect(j1.status).toBe('pending');
    expect(service.create('stock', '600000').id).toBe(j1.id);
    expect(service.create('etf', '600000').id).not.toBe(j1.id); // 不同类型不去重
  });

  it('任务状态与结果落库，新实例可从 DB 查询（重启恢复）', async () => {
    const db = createDb();
    const s1 = new JobManagerService(db);
    const job = s1.create('stock', '600000');
    await s1.run(job.id, async () => ({ code: '600000' }));

    const s2 = new JobManagerService(db); // 模拟重启
    const restored = s2.get(job.id);
    expect(restored).toBeDefined();
    expect(restored!.status).toBe('done');
    expect(restored!.result).toEqual({ code: '600000' });
  });

  it('重启后中断的 pending/running 任务被标记 failed，done 任务保留', async () => {
    const db = createDb();
    const s1 = new JobManagerService(db);
    const running = s1.create('stock', '600001');
    s1.update(running.id, { status: 'running' });
    const done = s1.create('etf', '510010');
    await s1.run(done.id, async () => 'ok');

    const s2 = new JobManagerService(db); // 模拟重启
    expect(s2.get(running.id)!.status).toBe('failed');
    expect(s2.get(running.id)!.error).toContain('restart');
    expect(s2.get(done.id)!.status).toBe('done');
  });

  it('全局并发不超过上限（简单信号量）', async () => {
    const db = createDb();
    const service = new JobManagerService(db);
    const blockers: Array<() => void> = [];
    const entered: number[] = [];
    const codes = ['c1', 'c2', 'c3', 'c4', 'c5'];
    const jobs = codes.map((code) => service.create('stock', code));
    const runs = jobs.map((job, i) =>
      service.run(job.id, async () => {
        entered.push(i);
        if (entered.length <= MAX_CONCURRENT) {
          await new Promise<void>((resolve) => blockers.push(resolve));
        }
        return i;
      }),
    );
    await waitFor(() => expect(entered.length).toBe(MAX_CONCURRENT));
    while (blockers.length) blockers.shift()!();
    await Promise.all(runs);
    expect(entered.length).toBe(codes.length);
  });

  it('排队中的任务保持 pending，拿到信号量后才是 running', async () => {
    const db = createDb();
    const service = new JobManagerService(db);
    const blockers: Array<() => void> = [];
    const codes = ['c1', 'c2', 'c3', 'c4', 'c5'];
    const jobs = codes.map((code) => service.create('stock', code));
    let started = 0;
    const runs = jobs.map((job) =>
      service.run(job.id, async () => {
        started += 1;
        // 只阻塞占满信号量的前 MAX_CONCURRENT 个，其余放行以便收尾
        if (started <= MAX_CONCURRENT) {
          await new Promise<void>((resolve) => blockers.push(resolve));
        }
      }),
    );
    await waitFor(() => expect(blockers.length).toBe(MAX_CONCURRENT));

    const statuses = jobs.map((j) => service.get(j.id)!.status);
    expect(statuses.filter((s) => s === 'running')).toHaveLength(MAX_CONCURRENT);
    expect(statuses.filter((s) => s === 'pending')).toHaveLength(
      codes.length - MAX_CONCURRENT,
    );

    while (blockers.length) blockers.shift()!();
    await Promise.all(runs);
  });

  it('对同一 job id 重复 run 只执行一次任务', async () => {
    const db = createDb();
    const service = new JobManagerService(db);
    const job = service.create('stock', '600000');
    const task = jest.fn(async () => 'ok');
    await Promise.all([service.run(job.id, task), service.run(job.id, task)]);
    expect(task).toHaveBeenCalledTimes(1);
    expect(service.get(job.id)!.status).toBe('done');
  });

  it('任务失败时记录错误并可查询', async () => {
    const db = createDb();
    const service = new JobManagerService(db);
    const job = service.create('stock', '600001');
    await service.run(job.id, async () => {
      throw new Error('boom');
    });
    expect(service.get(job.id)!.status).toBe('failed');
    expect(service.get(job.id)!.error).toBe('boom');
  });
});
