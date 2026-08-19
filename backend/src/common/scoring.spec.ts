import {
  ratingFromScore,
  signalFromScore,
  isWorthBuying,
  compositeScore5,
  holdDaysFromTrend,
  trendFromMa,
  momentumScore,
  volatilityScore,
  volumeScore,
} from './scoring';

describe('scoring', () => {
  describe('ratingFromScore', () => {
    const cases: Array<[number, string]> = [
      [100, 'S+'],
      [88, 'S+'],
      [87, 'S'],
      [75, 'S'],
      [74, 'A+'],
      [63, 'A+'],
      [62, 'A'],
      [50, 'A'],
      [49, 'B+'],
      [38, 'B+'],
      [37, 'B'],
      [25, 'B'],
      [24, 'C+'],
      [13, 'C+'],
      [12, 'C'],
      [6, 'C'],
      [5, 'D'],
      [0, 'D'],
    ];
    test.each(cases)('score %i -> %s', (score, expected) => {
      expect(ratingFromScore(score)).toBe(expected);
    });
  });

  describe('signalFromScore', () => {
    it('多头 + score>=65 -> BUY', () => {
      expect(signalFromScore(70, '多头')).toBe('BUY');
    });
    it('非多头 + score>=65 -> HOLD', () => {
      expect(signalFromScore(70, '震荡')).toBe('HOLD');
    });
    it('45<=score<65 -> HOLD', () => {
      expect(signalFromScore(50, '多头')).toBe('HOLD');
    });
    it('score<45 -> SELL', () => {
      expect(signalFromScore(30, '空头')).toBe('SELL');
    });
  });

  it('isWorthBuying', () => {
    expect(isWorthBuying('BUY')).toBe(1);
    expect(isWorthBuying('HOLD')).toBe(0);
    expect(isWorthBuying('SELL')).toBe(0);
  });

  it('compositeScore5 加权并在 0~100 内', () => {
    expect(compositeScore5(100, 100, 100, 100, 100)).toBeCloseTo(100);
    expect(compositeScore5(0, 0, 0, 0, 0)).toBe(0);
    const s = compositeScore5(80, 60, 50, 40, 70);
    expect(s).toBeCloseTo(0.25 * 80 + 0.2 * 60 + 0.2 * 50 + 0.15 * 40 + 0.2 * 70);
  });

  it('holdDaysFromTrend 多头给出持有天数，非多头为 0', () => {
    expect(holdDaysFromTrend('多头', 100)).toBeGreaterThan(0);
    expect(holdDaysFromTrend('空头', 50)).toBe(0);
  });

  it('trendFromMa', () => {
    expect(trendFromMa(10, 9, 8)).toBe('多头');
    expect(trendFromMa(8, 9, 10)).toBe('空头');
    expect(trendFromMa(10, 8, 9)).toBe('震荡');
  });

  it('momentumScore 涨幅适中得分最高', () => {
    expect(momentumScore(10)).toBeGreaterThan(momentumScore(50));
    expect(momentumScore(-20)).toBeLessThan(momentumScore(10));
  });

  it('volatilityScore 波动低得分高', () => {
    expect(volatilityScore(15)).toBeGreaterThan(volatilityScore(80));
  });

  it('volumeScore 温和放量最佳', () => {
    expect(volumeScore(1.5)).toBeGreaterThan(volumeScore(0.5));
    expect(volumeScore(1.5)).toBeGreaterThan(volumeScore(5));
  });
});
