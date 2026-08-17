import { Controller, Get, Param, Query } from '@nestjs/common';
import { KlineService, KlineQueryDto } from './kline.service';

@Controller()
export class KlineController {
  constructor(private readonly kline: KlineService) {}

  @Get('stocks/:code/kline')
  stockKline(@Param('code') code: string, @Query() q: KlineQueryDto) {
    return this.kline.listKline('stock', code, q);
  }

  @Get('etfs/:code/kline')
  etfKline(@Param('code') code: string, @Query() q: KlineQueryDto) {
    return this.kline.listKline('etf', code, q);
  }
}
