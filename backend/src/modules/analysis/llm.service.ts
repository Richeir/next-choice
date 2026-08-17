import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '../../config/config.service';

/** LLM 输出的结构化结果（映射自 llm-analysis.md §2 schema）。 */
export interface LlmResult {
  rating: string;
  isWorthBuying: boolean;
  holdDays: number;
  reason?: string;
  llmAnalysis?: string;
  // 回填基础信息表（股票）
  industry?: string;
  lastAmount?: number;
  pb?: number;
  fullName?: string;
  totalMarketCap?: number;
  high52w?: number;
  low52w?: number;
  // 回填基础信息表（ETF）
  category?: string;
  manager?: string;
  fundScale?: number;
}

export interface LlmContext {
  securityType: '股票' | 'ETF';
  basicInfo: string;
  klineSummary: string;
  technicalIndicators: string;
}

@Injectable()
export class LlmService {
  private readonly logger = new Logger(LlmService.name);

  constructor(private readonly config: ConfigService) {}

  /**
   * 调用 LLM 分析。无 API key 时返回 null，由调用方回退到纯技术面评分。
   */
  async analyze(_context: LlmContext): Promise<LlmResult | null> {
    const apiKey = process.env.ANALYSIS_LLM_API_KEY;
    if (!apiKey) {
      this.logger.warn('ANALYSIS_LLM_API_KEY not set; falling back to technical analysis');
      return null;
    }
    // 有 key 时走真实调用（后续迭代接入）。MVP0 若配置了 key 仍回退，避免不可控调用。
    this.logger.warn('LLM provider integration not implemented yet; falling back');
    return null;
  }
}
