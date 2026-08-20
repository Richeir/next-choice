import { AnalysisService } from './analysis.service';
import { TechnicalAnalysisService } from './technical-analysis.service';

/** 构造一个便于断言的技术面结果：趋势多头，dims 与 trend 可自由指定。 */
function makeTechnical(
  dims = { trend: 80, momentum: 50, valuation: 50, volume: 50, stability: 50 },
  trend: '多头' | '空头' | '震荡' = '多头',
): ReturnType<TechnicalAnalysisService['analyze']> {
  return {
    score: 0,
    signal: 'SELL',
    rating: 'D',
    isWorthBuying: 0,
    holdDays: 0,
    dims,
    ma5: null,
    ma20: null,
    ma60: null,
    trend,
    momentum20: null,
    volatility20: null,
    volumeRatio: null,
    note: '',
  };
}

function makeService() {
  const service = new AnalysisService(
    {} as never,
    new TechnicalAnalysisService() as never,
    {} as never,
    {} as never,
    {} as never,
    {} as never,
  );
  return service;
}

describe('AnalysisService.mergeLlm', () => {
  const service = makeService();

  it('LLM 存在时用 LLM 维度分合成', () => {
    const r = service.mergeLlm(makeTechnical(), {
      trend: 100,
      momentum: 100,
      valuation: 100,
      volume: 100,
      stability: 100,
      reason: '全面向好',
      llmAnalysis: '详细分析',
    });
    expect(r.score).toBe(100);
    expect(r.rating).toBe('S+');
    expect(r.signal).toBe('BUY'); // score>=65 且技术面多头
    expect(r.isWorthBuying).toBe(1);
    expect(r.holdDays).toBeGreaterThan(0);
    expect(r.llmAnalysis).toBe('详细分析');
  });

  it('LLM 为 null 时降级用 technical.dims，score/rating/signal 与降级分一致', () => {
    const r = service.mergeLlm(makeTechnical(), null);
    // 0.25*80 + 0.2*50 + 0.2*50 + 0.15*50 + 0.2*50 = 20 + 10 + 10 + 7.5 + 10 = 57.5
    expect(r.score).toBeCloseTo(57.5);
    expect(r.rating).toBe('A'); // >=50
    expect(r.signal).toBe('HOLD'); // 45 <= 57.5 < 65
    expect(r.isWorthBuying).toBe(0);
    expect(r.holdDays).toBe(22); // 趋势多头，持有天数 = round(10 + 57.5/100*20)
    expect(r.llmAnalysis).toBeNull();
  });

  it('LLM 高分但技术面空头时不会触发 BUY（信号方向以技术面均线为准）', () => {
    const r = service.mergeLlm(makeTechnical({ trend: 25, momentum: 50, valuation: 50, volume: 50, stability: 50 }, '空头'), {
      trend: 100,
      momentum: 100,
      valuation: 100,
      volume: 100,
      stability: 100,
      reason: 'x',
    });
    expect(r.score).toBe(100);
    expect(r.signal).toBe('HOLD'); // score>=65 但 trend !== 多头
    expect(r.isWorthBuying).toBe(0);
  });

  it('score/rating/signal 出自同一套权重与换算，口径一致', () => {
    const llmPath = service.mergeLlm(makeTechnical(), {
      trend: 70,
      momentum: 60,
      valuation: 55,
      volume: 65,
      stability: 50,
      reason: 'r',
    });
    const fallbackPath = service.mergeLlm(makeTechnical(), null);
    // 直接按 compositeScore5 权重核对 LLM 路径
    const expected = 0.25 * 70 + 0.2 * 60 + 0.2 * 55 + 0.15 * 65 + 0.2 * 50;
    expect(llmPath.score).toBeCloseTo(expected);
    // 一致性：rating/signal 都能由 score 推出
    expect(fallbackPath.rating).toBe('A');
    expect(fallbackPath.signal).toBe('HOLD');
  });
});
