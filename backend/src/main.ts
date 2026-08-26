import * as dotenv from 'dotenv';
import * as path from 'path';
import * as express from 'express';
import { existsSync } from 'fs';
// 从仓库根加载 .env（后端在 backend/ 下启动，cwd 默认不指向仓库根）
dotenv.config({ path: path.join(__dirname, '..', '..', '.env') });
import { NestFactory } from '@nestjs/core';
import { ValidationPipe } from '@nestjs/common';
import { NextFunction, Request, Response } from 'express';
import { AppModule } from './app.module';

/** 前端构建产物目录（frontend/ 下 `npm run build` 生成） */
const CLIENT_DIST = path.join(__dirname, '..', '..', 'frontend', 'dist');

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
  // 存在前端构建产物时单进程托管：静态资源 + 非 /api 的无扩展名 GET 回退 index.html（SPA history 路由）。
  // /api/* 一律交给 Nest 路由，未知 API 路径仍返回 JSON 404 而非页面。此中间件先于 Nest 路由注册，故须自行放行 /api。
  if (existsSync(path.join(CLIENT_DIST, 'index.html'))) {
    app.use(express.static(CLIENT_DIST));
    app.use((req: Request, res: Response, next: NextFunction) => {
      if (
        req.method === 'GET' &&
        !req.path.startsWith('/api/') &&
        req.path !== '/api' &&
        !path.extname(req.path)
      ) {
        res.sendFile(path.join(CLIENT_DIST, 'index.html'));
      } else {
        next();
      }
    });
  }
  const port = process.env.PORT || 3100;
  await app.listen(port);
  // eslint-disable-next-line no-console
  console.log(`Nest.js backend listening on http://localhost:${port}/api`);
}

void bootstrap();
