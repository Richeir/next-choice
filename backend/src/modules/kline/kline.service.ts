import { Injectable, BadRequestException } from '@nestjs/common';
import {
  KlineRepository,
  SecurityType,
  KlineFrequency,
  ADJUST_MAP,
} from './kline.repository';

const FREQUENCIES: KlineFrequency[] = ['daily', 'weekly', 'monthly'];

export interface KlineQueryDto {
  frequency?: KlineFrequency;
  adjust?: 'qfq' | 'raw';
  limit?: number;
  start?: string;
  end?: string;
}

@Injectable()
export class KlineService {
  constructor(private readonly repo: KlineRepository) {}

  listKline(type: SecurityType, code: string, query: KlineQueryDto) {
    const frequency = (query.frequency ?? 'daily') as KlineFrequency;
    if (!FREQUENCIES.includes(frequency)) {
      throw new BadRequestException(`invalid frequency: ${frequency}`);
    }
    const adjustKey = query.adjust ?? 'qfq';
    if (!(adjustKey in ADJUST_MAP)) {
      throw new BadRequestException(`invalid adjust: ${adjustKey}`);
    }
    const adjustflag = ADJUST_MAP[adjustKey];
    const rows = this.repo.list({
      type,
      code,
      frequency,
      adjustflag,
      limit: query.limit,
      start: query.start,
      end: query.end,
    });
    return { items: rows };
  }
}
