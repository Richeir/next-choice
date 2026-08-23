import { Injectable, NotFoundException } from '@nestjs/common';
import { AnalysisRepository } from './analysis.repository';
import { TechnicalAnalysisService, buildNote } from './technical-analysis.service';
import { LlmService, LlmContext, LlmResult, promptVersionOf } from './llm.service';
import { KlineRepository, SecurityType, KlineQuery } from '../kline/kline.repository';
import { JobManagerService } from '../../jobs/job-manager.service';
import { ConfigService } from '../../config/config.service';
import { rowToCamel } from '../../common/mapper';
import {
  compositeScore5,
  holdDaysFromTrend,
  isWorthBuying as isWorthBuyingSignal,
  ratingFromScore,
  signalFromScore,
} from '../../common/scoring';

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

  /**
   * 触发单只标的分析：异步执行，写入分析表并回填基础信息。
   * 同一标的有进行中（pending/running）任务时复用该任务，避免重复消耗 LLM。
   */
  trigger(type: SecurityType, code: string) {
    if (!this.analysisRepo.exists(type, code)) {
      throw new NotFoundException(`${type} ${code} not found`);
    }
    const job = this.jobs.create(type, code);
    // run() 自身对 job id 幂等：复用已有任务时不会重复执行（排队中的任务仍是 pending）
    void this.jobs.run(job.id, () => this.execute(type, code));
    return { accepted: true, jobId: job.id };
  }

  /** 查询任务；未知 id 返回 404（而非 fake failed 状态）。 */
  getJob(id: string) {
    const job = this.jobs.get(id);
    if (!job) {
      throw new NotFoundException(`job ${id} not found`);
    }
    return { jobId: job.id, status: job.status, result: job.result, error: job.error };
  }

  private async execute(type: SecurityType, code: string) {
    const info = this.analysisRepo.getInfo(type, code);
    if (!info) throw new NotFoundException(`${type} ${code} not found`);

    const config = this.config.get();
    // 股票用前复权（'2'）做趋势/技术分析；ETF 采集侧仅存不复权（'3'）数据
    // （新浪源不支持 ETF 复权），硬编码 '2' 会查不到任何 K 线导致分析失败。
    const adjustflag = type === 'stock' ? '2' : '3';
    const klineQuery: KlineQuery = {
      type,
      code,
      frequency: 'daily',
      adjustflag,
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

    // 分析日期取数据最后交易日（升序列表最后一行），避免 UTC 时区跨日记到前一天。
    const lastRow = klineRows[klineRows.length - 1];
    const date = String(lastRow.date);

    const final = this.mergeLlm(technical, llmResult);
    // note 的“综合评分”须与入库 score 同源：LLM 路径基于 final.score 重建，避免两套数字并存；
    // LLM 的 reason 追加到 note 末尾（文档约定 reason → note），不再丢弃。
    const note = llmResult
      ? buildNote(
          technical.trend,
          final.score,
          technical.momentum20,
          technical.volatility20,
          technical.volumeRatio,
        ) + (llmResult.reason ? `；${llmResult.reason}` : '')
      : technical.note;

    this.analysisRepo.insertAnalysis(type, code, {
      date,
      score: final.score,
      signal: final.signal,
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
      note,
      llmAnalysis: final.llmAnalysis,
      dims: JSON.stringify(final.dims),
      model: llmResult ? process.env.LLM_MODEL || config.model : null,
      promptVersion: llmResult ? promptVersionOf(config.promptTemplate) : null,
    });

    return rowToCamel(this.analysisRepo.getInfo(type, code) ?? {});
  }

  /**
   * 用 5 维维度分合成综合分并换算评级/信号/持有天数。
   * LLM 存在时用 LLM 的维度分，否则降级用技术面维度分（technical.dims）。
   * 无论哪条路径，score / rating / signal 都出自同一套权重与换算，口径一致。
   */
  mergeLlm(
    technical: ReturnType<TechnicalAnalysisService['analyze']>,
    llm: LlmResult | null,
  ) {
    const dims = llm
      ? {
          trend: llm.trend,
          momentum: llm.momentum,
          valuation: llm.valuation,
          volume: llm.volume,
          stability: llm.stability,
        }
      : technical.dims;
    const score = compositeScore5(
      dims.trend,
      dims.momentum,
      dims.valuation,
      dims.volume,
      dims.stability,
    );
    const signal = signalFromScore(score, technical.trend);
    return {
      score,
      signal,
      rating: ratingFromScore(score),
      isWorthBuying: isWorthBuyingSignal(signal),
      holdDays: holdDaysFromTrend(technical.trend, score),
      dims,
      llmAnalysis: llm?.llmAnalysis ?? llm?.reason ?? null,
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
