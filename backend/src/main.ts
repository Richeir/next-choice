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
  // 前端产物独立部署时不经 Vite 代理，需放行跨域；CORS_ORIGIN 逗号分隔，缺省放行全部
  const corsOrigin = process.env.CORS_ORIGIN?.split(',')
    .map((o) => o.trim())
    .filter(Boolean);
  app.enableCors({ origin: corsOrigin?.length ? corsOrigin : true });
  app.useGlobalPipes(
    new ValidationPipe({ transform: true, whitelist: true, forbidNonWhitelisted: false }),
  );
  // 没有它 DatabaseService 的 OnApplicationShutdown 在 SIGTERM 下不触发，WAL 不会干净关闭
  app.enableShutdownHooks();
  const port = process.env.PORT || 3100;
  await app.listen(port);
  // eslint-disable-next-line no-console
  console.log(`Nest.js backend listening on http://localhost:${port}/api`);
}

void bootstrap();
