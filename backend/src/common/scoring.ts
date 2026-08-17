/** 评分 / 评级 / 信号换算（纯函数，基于 db-design.md §6）。 */

export type Signal = 'BUY' | 'HOLD' | 'SELL';
export type Trend = '多头' | '空头' | '震荡';

/** 按 9 档区间由 0~100 综合评分换算买入评级。 */
export function ratingFromScore(score: number): string {
  if (score >= 88) return 'S+';
  if (score >= 75) return 'S';
  if (score >= 63) return 'A+';
  if (score >= 50) return 'A';
  if (score >= 38) return 'B+';
  if (score >= 25) return 'B';
  if (score >= 13) return 'C+';
  if (score >= 6) return 'C';
  return 'D';
}

/**
 * 由综合评分与趋势推导结论信号。
 * score ≥ 65 且多头 → BUY；45 ≤ score < 65 → HOLD；score < 45 → SELL。
 */
export function signalFromScore(score: number, trend: Trend): Signal {
  if (score >= 65 && trend === '多头') return 'BUY';
  if (score >= 45) return 'HOLD';
  return 'SELL';
}

export function isWorthBuying(signal: Signal): 0 | 1 {
  return signal === 'BUY' ? 1 : 0;
}

/** 综合评分 = 0.35×趋势 + 0.30×动量 + 0.15×波动 + 0.20×量能，各分量 0~100。 */
export function compositeScore(
  trendScore: number,
  momentumScore: number,
  volatilityScore: number,
  volumeScore: number,
): number {
  const score =
    0.35 * trendScore + 0.3 * momentumScore + 0.15 * volatilityScore + 0.2 * volumeScore;
  // 约束到 0~100
  return Math.max(0, Math.min(100, score));
}

/** 由趋势强度给出建议持有天数（多头较强则多，否则 0）。 */
export function holdDaysFromTrend(trend: Trend, score: number): number {
  if (trend === '多头') {
    // 多头越强持有天数越多（10~30 天）
    return Math.round(10 + (score / 100) * 20);
  }
  return 0;
}

/** 均线排列趋势：MA5>MA20>MA60 多头，反之为空头，否则震荡。 */
export function trendFromMa(ma5: number, ma20: number, ma60: number): Trend {
  if (ma5 > ma20 && ma20 > ma60) return '多头';
  if (ma5 < ma20 && ma20 < ma60) return '空头';
  return '震荡';
}

/** 趋势得分：多头排列高分，空头低分。 */
export function trendScore(trend: Trend): number {
  switch (trend) {
    case '多头':
      return 80;
    case '震荡':
      return 55;
    case '空头':
      return 25;
  }
}

/** 动量得分：近 20 日涨幅适中（5%~20%）最高，追高/暴跌压低。 */
export function momentumScore(momentum20: number): number {
  if (momentum20 >= 5 && momentum20 <= 20) return 90;
  if (momentum20 > 20 && momentum20 <= 40) return 70;
  if (momentum20 > 40) return 40; // 追高
  if (momentum20 >= 0 && momentum20 < 5) return 60;
  if (momentum20 < 0 && momentum20 >= -15) return 45;
  return 20; // 暴跌
}

/** 波动得分：年化波动率越低越稳、得分越高。 */
export function volatilityScore(annualizedVol20: number): number {
  if (annualizedVol20 <= 20) return 90;
  if (annualizedVol20 <= 40) return 70;
  if (annualizedVol20 <= 60) return 50;
  if (annualizedVol20 <= 100) return 30;
  return 10;
}

/** 量能得分：温和放量（量比 1.2~2.5）最佳，缩量/爆量减分。 */
export function volumeScore(volumeRatio: number): number {
  if (volumeRatio >= 1.2 && volumeRatio <= 2.5) return 90;
  if (volumeRatio >= 0.8 && volumeRatio < 1.2) return 65;
  if (volumeRatio > 2.5 && volumeRatio <= 4) return 55;
  if (volumeRatio < 0.8) return 30; // 缩量
  return 20; // 爆量
}
