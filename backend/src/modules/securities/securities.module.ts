import { Module } from '@nestjs/common';
import { SecuritiesController } from './securities.controller';
import { SecuritiesService } from './securities.service';
import { StockInfoRepository } from './repository/stock-info.repository';
import { EtfInfoRepository } from './repository/etf-info.repository';

@Module({
  controllers: [SecuritiesController],
  providers: [SecuritiesService, StockInfoRepository, EtfInfoRepository],
  exports: [SecuritiesService],
})
export class SecuritiesModule {}
