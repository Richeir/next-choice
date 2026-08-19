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

/** 合法评级枚举（llm-analysis.md §2）。 */
const RATINGS = ['S+', 'S', 'A+', 'A', 'B+', 'B', 'C+', 'C', 'D'];

const DEFAULT_BASE_URL = 'https://api.openai.com/v1';

@Injectable()
export class LlmService {
  private readonly logger = new Logger(LlmService.name);

  constructor(private readonly config: ConfigService) {}

  /**
   * 调用 LLM 分析。无 API key 或分析失败时返回 null，由调用方回退到纯技术面评分。
   */
  async analyze(context: LlmContext): Promise<LlmResult | null> {
    const apiKey = process.env.LLM_API_KEY;
    if (!apiKey) {
      this.logger.warn('LLM_API_KEY not set; falling back to technical analysis');
      return null;
    }

    const config = this.config.get();
    const baseUrl = (process.env.LLM_BASE_URL || DEFAULT_BASE_URL).replace(/\/+$/, '');
    const model = process.env.LLM_MODEL || config.model;
    const prompt = this.renderPrompt(config.promptTemplate, context);

    for (let attempt = 0; attempt <= config.maxRetries; attempt++) {
      if (attempt > 0) {
        await sleep(attempt * 200); // 轻量退避，避免打爆端点
      }
      try {
        const raw = await this.callOnce(baseUrl, model, prompt, config);
        const parsed = this.parseAndValidate(raw);
        if (parsed) return parsed;
        this.logger.warn(`LLM output invalid (attempt ${attempt + 1})`);
      } catch (err) {
        this.logger.warn(`LLM call failed (attempt ${attempt + 1}): ${(err as Error).message}`);
      }
    }
    this.logger.warn('LLM analysis failed after all retries; falling back to technical');
    return null;
  }

  private renderPrompt(template: string, context: LlmContext): string {
    return template
      .replace(/{{securityType}}/g, context.securityType)
      .replace(/{{basicInfo}}/g, context.basicInfo)
      .replace(/{{klineSummary}}/g, context.klineSummary)
      .replace(/{{technicalIndicators}}/g, context.technicalIndicators);
  }

  private async callOnce(
    baseUrl: string,
    model: string,
    prompt: string,
    config: { timeoutMs: number; temperature: number },
  ): Promise<string> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), config.timeoutMs);
    try {
      const res = await fetch(`${baseUrl}/chat/completions`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${process.env.LLM_API_KEY}`,
        },
        body: JSON.stringify({
          model,
          temperature: config.temperature,
          messages: [
            {
              role: 'system',
              content: '你是一个严谨的 A 股技术分析师，只输出符合要求的 JSON。',
            },
            { role: 'user', content: prompt },
          ],
        }),
        signal: controller.signal,
      });
      if (!res.ok) {
        throw new Error(`LLM endpoint returned ${res.status}`);
      }
      const data = (await res.json()) as {
        choices?: { message?: { content?: string } }[];
      };
      const content = data.choices?.[0]?.message?.content;
      if (!content) throw new Error('LLM response missing choices[0].message.content');
      return content;
    } finally {
      clearTimeout(timer);
    }
  }

  /** 解析 LLM 文本为 JSON 并校验 schema；不合法返回 null。 */
  private parseAndValidate(text: string): LlmResult | null {
    let obj: unknown;
    try {
      obj = JSON.parse(text);
    } catch {
      return null;
    }
    if (typeof obj !== 'object' || obj === null) return null;
    const o = obj as Record<string, unknown>;
    // 容忍字符串布尔（LLM 偶尔输出 "true"/"false"），归一化为布尔；非法类型视为无效
    let isWorthBuying: boolean | undefined;
    if (typeof o.isWorthBuying === 'boolean') {
      isWorthBuying = o.isWorthBuying;
    } else if (o.isWorthBuying === 'true') {
      isWorthBuying = true;
    } else if (o.isWorthBuying === 'false') {
      isWorthBuying = false;
    }
    if (
      typeof o.rating !== 'string' ||
      !RATINGS.includes(o.rating) ||
      isWorthBuying === undefined ||
      typeof o.holdDays !== 'number' ||
      !Number.isInteger(o.holdDays) ||
      o.holdDays < 0 ||
      o.holdDays > 365
    ) {
      return null;
    }
    return {
      rating: o.rating,
      isWorthBuying,
      holdDays: o.holdDays,
      reason: typeof o.reason === 'string' ? o.reason : undefined,
      llmAnalysis: typeof o.llmAnalysis === 'string' ? o.llmAnalysis : undefined,
      ...(typeof o.industry === 'string' ? { industry: o.industry } : {}),
      ...(typeof o.lastAmount === 'number' ? { lastAmount: o.lastAmount } : {}),
      ...(typeof o.pb === 'number' ? { pb: o.pb } : {}),
      ...(typeof o.fullName === 'string' ? { fullName: o.fullName } : {}),
      ...(typeof o.totalMarketCap === 'number' ? { totalMarketCap: o.totalMarketCap } : {}),
      ...(typeof o.high52w === 'number' ? { high52w: o.high52w } : {}),
      ...(typeof o.low52w === 'number' ? { low52w: o.low52w } : {}),
      ...(typeof o.category === 'string' ? { category: o.category } : {}),
      ...(typeof o.manager === 'string' ? { manager: o.manager } : {}),
      ...(typeof o.fundScale === 'number' ? { fundScale: o.fundScale } : {}),
    };
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
