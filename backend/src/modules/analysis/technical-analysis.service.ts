import { Injectable } from '@nestjs/common';
import {
  compositeScore5,
  holdDaysFromTrend,
  isWorthBuying,
  momentumScore,
  ratingFromScore,
  signalFromScore,
  trendFromMa,
  trendScore,
  volatilityScore,
  volumeScore,
  Signal,
  Trend,
} from '../../common/scoring';

const MIN_POINTS = 21;

export interface KlinePoint {
  date: string;
  close: number;
  volume: number;
}

export interface DimensionScores {
  trend: number;
  momentum: number;
  valuation: number;
  volume: number;
  stability: number;
}

export interface TechnicalResult {
  score: number;
  signal: Signal;
  rating: string;
  isWorthBuying: 0 | 1;
  holdDays: number;
  /** 各维度原始得分（LLM 缺失时用于降级，估值取中性 50）。 */
  dims: DimensionScores;
  ma5: number | null;
  ma20: number | null;
  ma60: number | null;
  trend: Trend;
  momentum20: number | null;
  volatility20: number | null;
  volumeRatio: number | null;
  note: string;
}

/** 对升序 K 线做纯技术面分析，产出评分 / 信号 / 评级与各项指标。 */
@Injectable()
export class TechnicalAnalysisService {
  analyze(points: KlinePoint[]): TechnicalResult {
    const closes = points.map((p) => p.close).filter((v) => typeof v === 'number' && !isNaN(v));
    // 至少需要 21 个收盘价才能评估动量/波动；否则按数据不足保守处理。
    if (closes.length < MIN_POINTS) {
      return {
        score: 0,
        signal: 'SELL',
        rating: 'D',
        isWorthBuying: 0,
        holdDays: 0,
        dims: { trend: 0, momentum: 0, valuation: 50, volume: 0, stability: 0 },
        ma5: null,
        ma20: null,
        ma60: null,
        trend: '震荡',
        momentum20: null,
        volatility20: null,
        volumeRatio: null,
        note: '数据不足，无法分析',
      };
    }

    const ma5 = sma(closes, 5);
    const ma20 = sma(closes, 20);
    const ma60 = sma(closes, 60);
    const trend = trendFromMa(
      ma5 ?? closes[closes.length - 1],
      ma20 ?? closes[closes.length - 1],
      ma60 ?? closes[closes.length - 1],
    );

    const momentum20 = momentumOverN(closes, 20);
    const volatility20 = annualizedVolatility(closes, 20);
    const volumeRatio = points.length >= 5 ? calcVolumeRatio(points, 5, 20) : null;

    const dims: DimensionScores = {
      trend: trendScore(trend),
      momentum: momentum20 !== null ? momentumScore(momentum20) : 50,
      valuation: 50, // 技术面无法判断估值，给中性分
      volume: volumeRatio !== null ? volumeScore(volumeRatio) : 50,
      stability: volatility20 !== null ? volatilityScore(volatility20) : 50,
    };
    const score = compositeScore5(
      dims.trend,
      dims.momentum,
      dims.valuation,
      dims.volume,
      dims.stability,
    );

    const signal = signalFromScore(score, trend);
    const rating = ratingFromScore(score);
    const holdDays = holdDaysFromTrend(trend, score);
    const note = buildNote(trend, score, momentum20, volatility20, volumeRatio);

    return {
      score,
      signal,
      rating,
      isWorthBuying: isWorthBuying(signal),
      holdDays,
      dims,
      ma5,
      ma20,
      ma60,
      trend,
      momentum20,
      volatility20,
      volumeRatio,
      note,
    };
  }
}

function sma(values: number[], window: number): number | null {
  if (values.length < window) return null;
  const slice = values.slice(values.length - window);
  return slice.reduce((a, b) => a + b, 0) / window;
}

/** 近 N 日涨跌幅（%），数据不足返回 null。 */
function momentumOverN(values: number[], n: number): number | null {
  if (values.length < n + 1) return null;
  const prev = values[values.length - n - 1];
  const last = values[values.length - 1];
  if (!prev) return null;
  return ((last - prev) / prev) * 100;
}

/** 近 N 日日收益的年化波动率（%）。 */
function annualizedVolatility(values: number[], n: number): number | null {
  if (values.length < n + 1) return null;
  const slice = values.slice(values.length - (n + 1));
  const returns: number[] = [];
  for (let i = 1; i < slice.length; i++) {
    if (slice[i - 1]) returns.push(slice[i] / slice[i - 1] - 1);
  }
  if (returns.length < 2) return null;
  const mean = returns.reduce((a, b) => a + b, 0) / returns.length;
  const variance =
    returns.reduce((acc, r) => acc + (r - mean) * (r - mean), 0) / (returns.length - 1);
  const dailyStd = Math.sqrt(variance);
  return dailyStd * Math.sqrt(252) * 100;
}

/** 量比 = 近 short 日均量 / 近 long 日均量。 */
function calcVolumeRatio(
  points: KlinePoint[],
  short: number,
  long: number,
): number | null {
  const vols = points
    .map((p) => p.volume)
    .filter((v) => typeof v === 'number' && v > 0);
  if (vols.length < long) return null;
  const shortSlice = vols.slice(vols.length - short);
  const longSlice = vols.slice(vols.length - long);
  const shortAvg = shortSlice.reduce((a, b) => a + b, 0) / shortSlice.length;
  const longAvg = longSlice.reduce((a, b) => a + b, 0) / longSlice.length;
  if (longAvg === 0) return null;
  return shortAvg / longAvg;
}

export function buildNote(
  trend: Trend,
  score: number,
  momentum20: number | null,
  volatility20: number | null,
  volumeRatio: number | null,
): string {
  const parts: string[] = [`趋势：${trend}`, `综合评分：${Math.round(score)}`];
  if (momentum20 !== null) parts.push(`近20日涨幅：${momentum20.toFixed(1)}%`);
  if (volatility20 !== null) parts.push(`年化波动率：${volatility20.toFixed(1)}%`);
  if (volumeRatio !== null) parts.push(`量比：${volumeRatio.toFixed(2)}`);
  return parts.join('；');
}
