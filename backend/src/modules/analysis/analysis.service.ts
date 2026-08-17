import { Injectable, NotFoundException } from '@nestjs/common';
import { AnalysisRepository } from './analysis.repository';
import { TechnicalAnalysisService } from './technical-analysis.service';
import { LlmService, LlmContext, LlmResult } from './llm.service';
import { KlineRepository, SecurityType, KlineQuery } from '../kline/kline.repository';
import { JobManagerService } from '../../jobs/job-manager.service';
import { ConfigService } from '../../config/config.service';
import { rowToCamel } from '../../common/mapper';

@Injectable()
export class AnalysisService {
  constructor(
    private readonly analysisRepo: AnalysisRepository,
    private readonly technical: TechnicalAnalysisService,
    private readonly llm: LlmService,
    private readonly klineRepo: KlineRepository,
    private readonly jobs: JobManagerService,
    private readonly config: ConfigService,
  ) {}

  /** 触发单只标的分析：异步执行，写入分析表并回填基础信息。 */
  trigger(type: SecurityType, code: string) {
    if (!this.analysisRepo.exists(type, code)) {
      throw new NotFoundException(`${type} ${code} not found`);
    }
    const job = this.jobs.create();
    void this.jobs.run(job.id, () => this.execute(type, code));
    return { accepted: true, jobId: job.id };
  }

  getJob(id: string) {
    const job = this.jobs.get(id);
    if (!job) {
      return { jobId: id, status: 'failed', result: null, error: 'job not found' };
    }
    return { jobId: job.id, status: job.status, result: job.result, error: job.error };
  }

  private async execute(type: SecurityType, code: string) {
    const info = this.analysisRepo.getInfo(type, code);
    if (!info) throw new NotFoundException(`${type} ${code} not found`);

    const config = this.config.get();
    const klineQuery: KlineQuery = {
      type,
      code,
      frequency: 'daily',
      adjustflag: '2', // 前复权，用于趋势/技术分析
      limit: config.klineLimit,
    };
    const klineRows = this.klineRepo.list(klineQuery);
    if (klineRows.length === 0) {
      throw new Error(`no kline data for ${code}`);
    }
    const points = klineRows.map((r) => ({
      date: String(r.date),
      close: Number(r.close),
      volume: Number(r.volume),
    }));

    const technical = this.technical.analyze(points);

    const llmResult = await this.llm.analyze(this.buildLlmContext(type, info, klineRows, technical));

    const today = new Date().toISOString().slice(0, 10);
    const final = this.mergeLlm(technical, llmResult);

    this.analysisRepo.insertAnalysis(type, code, {
      date: today,
      score: technical.score,
      signal: technical.signal,
      rating: final.rating,
      isWorthBuying: final.isWorthBuying,
      holdDays: final.holdDays,
      ma5: technical.ma5,
      ma20: technical.ma20,
      ma60: technical.ma60,
      trend: technical.trend,
      momentum20: technical.momentum20,
      volatility20: technical.volatility20,
      volumeRatio: technical.volumeRatio,
      note: technical.note,
      llmAnalysis: final.llmAnalysis,
    });

    if (llmResult) {
      this.analysisRepo.backfillInfo(type, code, llmResult);
    }

    return rowToCamel(this.analysisRepo.getInfo(type, code) ?? {});
  }

  private mergeLlm(
    technical: ReturnType<TechnicalAnalysisService['analyze']>,
    llm: LlmResult | null,
  ) {
    if (!llm) {
      return {
        rating: technical.rating,
        isWorthBuying: technical.isWorthBuying,
        holdDays: technical.holdDays,
        llmAnalysis: null,
      };
    }
    return {
      rating: llm.rating,
      isWorthBuying: llm.isWorthBuying ? 1 : 0,
      holdDays: llm.holdDays,
      llmAnalysis: llm.llmAnalysis ?? llm.reason ?? null,
    };
  }

  private buildLlmContext(
    type: SecurityType,
    info: Record<string, unknown>,
    klineRows: Record<string, unknown>[],
    technical: ReturnType<TechnicalAnalysisService['analyze']>,
  ): LlmContext {
    const securityType = type === 'stock' ? '股票' : 'ETF';
    const basicInfo = JSON.stringify(info);
    const klineSummary = klineRows
      .slice(-30)
      .map((r) => `${r.date}:c=${r.close}`)
      .join('\n');
    const technicalIndicators = JSON.stringify({
      ma5: technical.ma5,
      ma20: technical.ma20,
      ma60: technical.ma60,
      trend: technical.trend,
      momentum20: technical.momentum20,
      volatility20: technical.volatility20,
      volumeRatio: technical.volumeRatio,
      score: Math.round(technical.score),
    });
    return { securityType, basicInfo, klineSummary, technicalIndicators };
  }
}
