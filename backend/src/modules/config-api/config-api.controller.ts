import { Body, Controller, Get, Put } from '@nestjs/common';
import { ConfigApiService } from './config-api.service';

@Controller('config/analysis')
export class ConfigApiController {
  constructor(private readonly service: ConfigApiService) {}

  @Get()
  get() {
    return this.service.get();
  }

  @Put()
  update(@Body() body: Record<string, unknown>) {
    return this.service.update(body);
  }
}
