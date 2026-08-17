import { Injectable } from '@nestjs/common';
import { v4 as uuidv4 } from 'uuid';

export type JobStatus = 'pending' | 'running' | 'done' | 'failed';

export interface Job {
  id: string;
  status: JobStatus;
  result: unknown;
  error?: string;
  createdAt: number;
}

@Injectable()
export class JobManagerService {
  private readonly jobs = new Map<string, Job>();

  create(status: JobStatus = 'pending'): Job {
    const job: Job = {
      id: uuidv4(),
      status,
      result: null,
      createdAt: Date.now(),
    };
    this.jobs.set(job.id, job);
    return job;
  }

  get(id: string): Job | undefined {
    return this.jobs.get(id);
  }

  update(id: string, patch: Partial<Job>): Job | undefined {
    const job = this.jobs.get(id);
    if (!job) return undefined;
    Object.assign(job, patch);
    return job;
  }

  /** 异步执行任务：running → done / failed。 */
  async run(id: string, task: () => Promise<unknown>): Promise<void> {
    this.update(id, { status: 'running', result: null });
    try {
      const result = await task();
      this.update(id, { status: 'done', result });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      this.update(id, { status: 'failed', error: message });
    }
  }
}
