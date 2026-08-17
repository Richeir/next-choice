import { Controller, Get, Param, Post } from '@nestjs/common';
import { AnalysisService } from './analysis.service';

@Controller()
export class AnalysisController {
  constructor(private readonly analysis: AnalysisService) {}

  @Post('stocks/:code/analyze')
  analyzeStock(@Param('code') code: string) {
    return this.analysis.trigger('stock', code);
  }

  @Post('etfs/:code/analyze')
  analyzeEtf(@Param('code') code: string) {
    return this.analysis.trigger('etf', code);
  }

  @Get('jobs/:jobId')
  getJob(@Param('jobId') jobId: string) {
    return this.analysis.getJob(jobId);
  }
}
