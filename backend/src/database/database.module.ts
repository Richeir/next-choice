import { Global, Module } from '@nestjs/common';
import { DatabaseService, DATABASE_SERVICE, resolveDbPath } from './database.service';
import * as path from 'path';

@Global()
@Module({
  providers: [
    {
      provide: DATABASE_SERVICE,
      useFactory: () => {
        const schemaPath = path.join(__dirname, '..', '..', 'database', 'schema.sql');
        return new DatabaseService({ path: resolveDbPath(), schemaPath });
      },
    },
  ],
  exports: [DATABASE_SERVICE],
})
export class DatabaseModule {}
