import { LlmService, LlmContext } from './llm.service';
import { ConfigService } from '../../config/config.service';

const baseConfig = {
  model: 'gpt-4o',
  promptTemplate: '模板 {{securityType}} {{basicInfo}} {{klineSummary}} {{technicalIndicators}}',
  timeoutMs: 1000,
  maxRetries: 2,
  klineLimit: 120,
  temperature: 0.2,
  updatedAt: null,
};

const context: LlmContext = {
  securityType: '股票',
  basicInfo: '{"code":"600000"}',
  klineSummary: '2024-01-01:c=10',
  technicalIndicators: '{"ma5":10}',
};

function makeService(
  env: Record<string, string | undefined> = {},
  configOverrides: Partial<typeof baseConfig> = {},
) {
  const config = {
    get: () => ({ ...baseConfig, ...configOverrides }),
  } as unknown as ConfigService;
  const service = new LlmService(config);
  const backup: Record<string, string | undefined> = {};
  for (const [k, v] of Object.entries(env)) {
    backup[k] = process.env[k];
    if (v === undefined) delete process.env[k];
    else process.env[k] = v;
  }
  return { service, restore: () => {
    for (const [k, v] of Object.entries(backup)) {
      if (v === undefined) delete process.env[k];
      else process.env[k] = v;
    }
  } };
}

const jsonResponse = (content: string) =>
  ({ choices: [{ message: { content } }] });

describe('LlmService', () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
    jest.useRealTimers();
  });

  it('未配置 API key 时返回 null（回退到技术面评分）', async () => {
    const { service, restore } = makeService({ LLM_API_KEY: undefined });
    await expect(service.analyze(context)).resolves.toBeNull();
    restore();
  });

  it('正常响应时解析并返回结构化结果', async () => {
    const content = JSON.stringify({
      trend: 70,
      momentum: 60,
      valuation: 55,
      volume: 65,
      stability: 50,
      reason: '趋势向好',
      llmAnalysis: '详细分析',
    });
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(jsonResponse(content)),
    }) as unknown as typeof fetch;

    const { service, restore } = makeService({ LLM_API_KEY: 'sk-test' });
    const result = await service.analyze(context);
    expect(result).toEqual({
      trend: 70,
      momentum: 60,
      valuation: 55,
      volume: 65,
      stability: 50,
      reason: '趋势向好',
      llmAnalysis: '详细分析',
    });
    restore();
  });

  it('构造请求时使用 base URL、model 与提示词渲染', async () => {
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(jsonResponse(JSON.stringify({
        trend: 60, momentum: 50, valuation: 55, volume: 65, stability: 50, reason: 'r',
      }))),
    });
    global.fetch = fetchMock as unknown as typeof fetch;

    const { service, restore } = makeService({
      LLM_API_KEY: 'sk-test',
      LLM_BASE_URL: 'https://proxy.example.com/v1/',
      LLM_MODEL: 'gpt-4o-mini',
    });
    await service.analyze(context);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('https://proxy.example.com/v1/chat/completions');
    const body = JSON.parse(init.body as string);
    expect(body.model).toBe('gpt-4o-mini');
    expect(body.temperature).toBe(baseConfig.temperature);
    expect(body.response_format).toEqual({ type: 'json_object' });
    const userMsg = body.messages.find((m: { role: string }) => m.role === 'user').content;
    expect(userMsg).toContain('股票');
    expect(userMsg).toContain('{"code":"600000"}');
    restore();
  });

  it('维度得分越界时重试并在耗尽重试后返回 null', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(jsonResponse(JSON.stringify({
        trend: 120, momentum: 60, valuation: 55, volume: 65, stability: 50, reason: 'r',
      }))),
    }) as unknown as typeof fetch;

    const { service, restore } = makeService({ LLM_API_KEY: 'sk-test' });
    await expect(service.analyze(context)).resolves.toBeNull();
    // 初始 1 次 + maxRetries 次重试
    expect(global.fetch as unknown as jest.Mock).toHaveBeenCalledTimes(3);
    restore();
  });

  it('拒绝字符串维度分并重试，重试后返回 null（不落库脏数据）', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(jsonResponse(JSON.stringify({
        trend: '70', momentum: 60, valuation: 55, volume: 65, stability: 50, reason: 'ok',
      }))),
    }) as unknown as typeof fetch;

    const { service, restore } = makeService({ LLM_API_KEY: 'sk-test' });
    await expect(service.analyze(context)).resolves.toBeNull();
    restore();
  });

  it('LLM 端点异常时重试并最终返回 null', async () => {
    global.fetch = jest.fn()
      .mockRejectedValueOnce(new Error('network'))
      .mockRejectedValueOnce(new Error('network'))
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve(jsonResponse(JSON.stringify({
          trend: 70, momentum: 60, valuation: 55, volume: 65, stability: 50, reason: 'ok',
        }))),
      }) as unknown as typeof fetch;

    const { service, restore } = makeService({ LLM_API_KEY: 'sk-test' });
    const result = await service.analyze(context);
    expect(result).toEqual({
      trend: 70, momentum: 60, valuation: 55, volume: 65, stability: 50, reason: 'ok',
    });
    restore();
  });
});

describe('LlmService 重试策略', () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
    jest.useRealTimers();
  });

  it('4xx（非 429）不可重试：直接返回 null，只调用一次', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 400,
    }) as unknown as typeof fetch;

    const { service, restore } = makeService({ LLM_API_KEY: 'sk-test' });
    await expect(service.analyze(context)).resolves.toBeNull();
    expect(global.fetch as unknown as jest.Mock).toHaveBeenCalledTimes(1);
    restore();
  });

  it('429 限流：按 maxRetries 重试后返回 null', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 429,
    }) as unknown as typeof fetch;

    const { service, restore } = makeService({ LLM_API_KEY: 'sk-test' });
    await expect(service.analyze(context)).resolves.toBeNull();
    // 初始 1 次 + maxRetries 次重试
    expect(global.fetch as unknown as jest.Mock).toHaveBeenCalledTimes(3);
    restore();
  });
});
