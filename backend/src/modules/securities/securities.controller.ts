import { Controller, Get, Param, Query } from '@nestjs/common';
import { SecuritiesService } from './securities.service';
import { ListQueryDto, AnalysisPageDto } from '../../common/list-query.dto';

@Controller()
export class SecuritiesController {
  constructor(private readonly securities: SecuritiesService) {}

  @Get('stocks')
  listStocks(@Query() q: ListQueryDto) {
    return this.securities.listStocks(q);
  }

  @Get('stocks/:code')
  getStock(@Param('code') code: string) {
    return this.securities.getStockDetail(code);
  }

  @Get('stocks/:code/analysis')
  getStockAnalysis(@Param('code') code: string, @Query() q: AnalysisPageDto) {
    return this.securities.listStockAnalysis(code, q.page ?? 1, q.pageSize ?? 20);
  }

  @Get('etfs')
  listEtfs(@Query() q: ListQueryDto) {
    return this.securities.listEtfs(q);
  }

  @Get('etfs/:code')
  getEtf(@Param('code') code: string) {
    return this.securities.getEtfDetail(code);
  }

  @Get('etfs/:code/analysis')
  getEtfAnalysis(@Param('code') code: string, @Query() q: AnalysisPageDto) {
    return this.securities.listEtfAnalysis(code, q.page ?? 1, q.pageSize ?? 20);
  }
}
