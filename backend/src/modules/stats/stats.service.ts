import { Injectable } from '@nestjs/common';
import { StatsRepository, StatsRow } from './stats.repository';

const CACHE_TTL_MS = 10 * 60 * 1000; // 10 分钟

@Injectable()
export class StatsService {
  private cache: StatsRow | null = null;
  private cachedAt = 0;

  constructor(private readonly repo: StatsRepository) {}

  async getStats(): Promise<StatsRow> {
    const now = Date.now();
    if (this.cache && now - this.cachedAt < CACHE_TTL_MS) {
      return this.cache;
    }
    const fresh = this.repo.getStats();
    this.cache = fresh;
    this.cachedAt = now;
    return fresh;
  }
}
