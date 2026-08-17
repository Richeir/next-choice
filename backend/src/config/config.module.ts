import { Global, Module } from '@nestjs/common';
import { ConfigService } from './config.service';
import { DatabaseModule } from '../database/database.module';

@Global()
@Module({
  imports: [DatabaseModule],
  providers: [ConfigService],
  exports: [ConfigService],
})
export class ConfigModule {}
