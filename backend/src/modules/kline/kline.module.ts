import { Module } from '@nestjs/common';
import { KlineController } from './kline.controller';
import { KlineService } from './kline.service';
import { KlineRepository } from './kline.repository';

@Module({
  controllers: [KlineController],
  providers: [KlineService, KlineRepository],
  exports: [KlineService, KlineRepository],
})
export class KlineModule {}
