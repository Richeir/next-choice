import * as dotenv from 'dotenv';
import * as path from 'path';
// 从仓库根加载 .env（后端在 backend/ 下启动，cwd 默认不指向仓库根）
dotenv.config({ path: path.join(__dirname, '..', '..', '.env') });
import { NestFactory } from '@nestjs/core';
import { ValidationPipe } from '@nestjs/common';
import { AppModule } from './app.module';

async function bootstrap() {
  const app = await NestFactory.create(AppModule);
  app.setGlobalPrefix('api');
  app.useGlobalPipes(
    new ValidationPipe({ transform: true, whitelist: true, forbidNonWhitelisted: false }),
  );
  const port = process.env.PORT || 3100;
  await app.listen(port);
  // eslint-disable-next-line no-console
  console.log(`Nest.js backend listening on http://localhost:${port}/api`);
}

void bootstrap();
