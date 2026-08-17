import { Module } from '@nestjs/common';
import { DatabaseModule } from './database/database.module';
import { ConfigModule } from './config/config.module';
import { JobsModule } from './jobs/jobs.module';
import { StatsModule } from './modules/stats/stats.module';
import { SecuritiesModule } from './modules/securities/securities.module';
import { KlineModule } from './modules/kline/kline.module';
import { AnalysisModule } from './modules/analysis/analysis.module';
import { ConfigApiModule } from './modules/config-api/config-api.module';

@Module({
  imports: [
    DatabaseModule,
    ConfigModule,
    JobsModule,
    StatsModule,
    SecuritiesModule,
    KlineModule,
    AnalysisModule,
    ConfigApiModule,
  ],
})
export class AppModule {}
