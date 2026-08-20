import { Injectable, Logger } from '@nestjs/common';
import { createHash } from 'crypto';
import { ConfigService } from '../../config/config.service';

/** 评分模型的 5 个维度（均 0~100，越高越有利）。 */
export const DIMENSIONS = ['trend', 'momentum', 'valuation', 'volume', 'stability'] as const;

export type Dimension = (typeof DIMENSIONS)[number];

/** LLM 输出的结构化结果：各维度得分（系统负责合成综合分与换算评级）。 */
export interface LlmResult {
  trend: number;
  momentum: number;
  valuation: number;
  volume: number;
  stability: number;
  reason?: string;
  llmAnalysis?: string;
}

export interface LlmContext {
  securityType: '股票' | 'ETF';
  basicInfo: string;
  klineSummary: string;
  technicalIndicators: string;
}

const DEFAULT_BASE_URL = 'https://api.openai.com/v1';

/** LLM 端点返回非 2xx 时抛出，携带 HTTP 状态码用于重试决策。 */
class LlmHttpError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

/**
 * 提示词模板版本：模板内容 SHA-1 前 8 位。
 * 模板一变版本即变，用于回看某个分数的 prompt 版本（存于分析表 prompt_version）。
 */
export function promptVersionOf(template: string): string {
  return createHash('sha1').update(template).digest('hex').slice(0, 8);
}

/** 指数退避：429 起步更久（500ms），其余 200ms，封顶 2s。 */
function backoffMs(attempt: number, rateLimited: boolean): number {
  const base = rateLimited ? 500 : 200;
  return Math.min(2000, base * 2 ** attempt);
}

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
      let rateLimited = false;
      try {
        const raw = await this.callOnce(baseUrl, model, prompt, config);
        const parsed = this.parseAndValidate(raw);
        if (parsed) return parsed;
        this.logger.warn(`LLM output invalid (attempt ${attempt + 1})`);
      } catch (err) {
        const status = err instanceof LlmHttpError ? err.status : undefined;
        rateLimited = status === 429;
        // 4xx（除 429）为不可重试错误：直接放弃，避免空耗重试
        if (status !== undefined && status >= 400 && status < 500 && status !== 429) {
          this.logger.warn(
            `LLM call failed (attempt ${attempt + 1}, non-retryable HTTP ${status}): ${(err as Error).message}`,
          );
          return null;
        }
        this.logger.warn(`LLM call failed (attempt ${attempt + 1}): ${(err as Error).message}`);
      }
      if (attempt < config.maxRetries) {
        await sleep(backoffMs(attempt, rateLimited));
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
          // 让端点直接返回 JSON 对象，降低解析失败与重试概率
          response_format: { type: 'json_object' },
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
        throw new LlmHttpError(`LLM endpoint returned ${res.status}`, res.status);
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
    // 校验 5 个维度得分均为 0~100 的数值；任一非法则整次丢弃并重试
    const dims: Record<Dimension, number> = {} as Record<Dimension, number>;
    for (const dim of DIMENSIONS) {
      const v = o[dim];
      if (typeof v !== 'number' || v < 0 || v > 100) return null;
      dims[dim] = v;
    }
    return {
      trend: dims.trend,
      momentum: dims.momentum,
      valuation: dims.valuation,
      volume: dims.volume,
      stability: dims.stability,
      reason: typeof o.reason === 'string' ? o.reason : undefined,
      llmAnalysis: typeof o.llmAnalysis === 'string' ? o.llmAnalysis : undefined,
    };
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
