import { TechnicalAnalysisService, KlinePoint } from './technical-analysis.service';

function risingSeries(n: number, start = 10, step = 0.1): KlinePoint[] {
  const points: KlinePoint[] = [];
  for (let i = 0; i < n; i++) {
    const close = start + i * step;
    points.push({
      date: `2024-01-${String((i % 28) + 1).padStart(2, '0')}`,
      close,
      volume: 1_000_000,
    });
  }
  return points;
}

describe('TechnicalAnalysisService', () => {
  const service = new TechnicalAnalysisService();

  it('上升趋势给出多头与正评分', () => {
    const r = service.analyze(risingSeries(80));
    expect(r.trend).toBe('多头');
    expect(r.score).toBeGreaterThan(0);
    expect(r.ma5).not.toBeNull();
    expect(r.ma20).not.toBeNull();
    expect(r.ma60).not.toBeNull();
    expect(r.momentum20).toBeGreaterThan(0);
  });

  it('数据不足时给出兜底结果', () => {
    const r = service.analyze([{ date: '2024-01-01', close: 10, volume: 1 }]);
    expect(r.trend).toBe('震荡');
    expect(r.score).toBe(0);
    expect(r.signal).toBe('SELL');
    expect(r.ma5).toBeNull();
  });

  it('均线与量比计算正确', () => {
    const points = risingSeries(60);
    const r = service.analyze(points);
    const closes = points.map((p) => p.close);
    const expectMa5 = closes.slice(-5).reduce((a, b) => a + b, 0) / 5;
    expect(r.ma5).toBeCloseTo(expectMa5, 5);
    expect(r.volumeRatio).toBeCloseTo(1, 5); // 恒定成交量 → 量比 1
  });

  it('下跌序列给出空头', () => {
    const falling: KlinePoint[] = [];
    for (let i = 0; i < 80; i++) {
      falling.push({
        date: `2024-01-${String((i % 28) + 1).padStart(2, '0')}`,
        close: 100 - i * 0.1,
        volume: 1_000_000,
      });
    }
    expect(service.analyze(falling).trend).toBe('空头');
  });
});

describe('TechnicalAnalysisService MA60 数据不足降级', () => {
  const service = new TechnicalAnalysisService();

  it('21~59 根时 MA60 为 null，趋势降级用 MA5/MA20 判断并给出正评分', () => {
    const r = service.analyze(risingSeries(40));
    expect(r.ma60).toBeNull();
    expect(r.ma5).not.toBeNull();
    expect(r.ma20).not.toBeNull();
    expect(r.trend).toBe('多头'); // 上升序列 → MA5 > MA20
    expect(r.score).toBeGreaterThan(0);
  });

  it('下跌且仅 40 根时降级为空头', () => {
    const falling: KlinePoint[] = [];
    for (let i = 0; i < 40; i++) {
      falling.push({
        date: `2024-01-${String((i % 28) + 1).padStart(2, '0')}`,
        close: 100 - i * 0.1,
        volume: 1_000_000,
      });
    }
    const r = service.analyze(falling);
    expect(r.ma60).toBeNull();
    expect(r.trend).toBe('空头');
  });
});
