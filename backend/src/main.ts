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
