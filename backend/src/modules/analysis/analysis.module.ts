import { Module } from '@nestjs/common';
import { AnalysisController } from './analysis.controller';
import { AnalysisService } from './analysis.service';
import { AnalysisRepository } from './analysis.repository';
import { TechnicalAnalysisService } from './technical-analysis.service';
import { LlmService } from './llm.service';
import { KlineModule } from '../kline/kline.module';

@Module({
  imports: [KlineModule],
  controllers: [AnalysisController],
  providers: [
    AnalysisService,
    AnalysisRepository,
    TechnicalAnalysisService,
    LlmService,
  ],
})
export class AnalysisModule {}
