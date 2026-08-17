import { Injectable } from '@nestjs/common';
import { ConfigService } from '../../config/config.service';

@Injectable()
export class ConfigApiService {
  constructor(private readonly config: ConfigService) {}

  get() {
    return this.config.get();
  }

  update(patch: Record<string, unknown>) {
    const allowed: Record<string, unknown> = {};
    for (const key of [
      'model',
      'promptTemplate',
      'timeoutMs',
      'maxRetries',
      'klineLimit',
      'temperature',
    ]) {
      if (patch[key] !== undefined) {
        allowed[key] = patch[key];
      }
    }
    return this.config.update(allowed);
  }
}
