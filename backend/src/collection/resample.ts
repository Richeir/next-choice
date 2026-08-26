import { CollectionError } from './errors';
import { KlineRow } from './normalize';

export type KlineFreq = 'weekly' | 'monthly';

/** 该日期所在周的周一（UTC 语义，等价 pandas Period('W') 的 Mon-Sun 分组）。 */
function weekKey(date: string): string {
  const [y, m, d] = date.split('-').map(Number);
  const t = Date.UTC(y, m - 1, d);
  const dow = new Date(t).getUTCDay();
  const monday = t - ((dow + 6) % 7) * 86400000;
  return new Date(monday).toISOString().slice(0, 10);
}

const monthKey = (date: string): string => date.slice(0, 7);

/**
 * 日 K -> 周/月 K（对齐 resample_kline）：
 * date 取组内最后交易日；open=first/high=max/low=min/close=last，
 * volume/amount 求和；preclose 为上一组 close；turn 置 null。
 */
export function resampleKline(
  rows: readonly KlineRow[],
  freq: KlineFreq,
): KlineRow[] {
  if (freq !== 'weekly' && freq !== 'monthly') {
    throw new CollectionError(`resample freq must be weekly/monthly, got ${freq}`);
  }
  const keyOf = freq === 'weekly' ? weekKey : monthKey;
  const sorted = [...rows].sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));

  const groups: Array<{ key: string; bars: KlineRow[] }> = [];
  for (const row of sorted) {
    const key = keyOf(row.date);
    const lastGroup = groups[groups.length - 1];
    if (lastGroup && lastGroup.key === key) {
      lastGroup.bars.push(row);
    } else {
      groups.push({ key, bars: [row] });
    }
  }

  const agg = groups.map(({ bars }) => {
    const sum = (pick: (r: KlineRow) => number | null): number | null => {
      let total = 0;
      let seen = false;
      for (const r of bars) {
        const v = pick(r);
        if (v !== null) {
          total += v;
          seen = true;
        }
      }
      return seen ? total : null;
    };
    const first = bars[0];
    const last = bars[bars.length - 1];
    return {
      date: last.date,
      open: first.open,
      high: bars.reduce<number | null>(
        (acc, r) => (r.high !== null && (acc === null || r.high > acc) ? r.high : acc),
        null,
      ),
      low: bars.reduce<number | null>(
        (acc, r) => (r.low !== null && (acc === null || r.low < acc) ? r.low : acc),
        null,
      ),
      close: last.close,
      volume: sum((r) => r.volume),
      amount: sum((r) => r.amount),
    };
  });

  // 组间 preclose/pctChg 链式计算
  let prevClose: number | null = null;
  return agg.map((g) => {
    const preclose = prevClose;
    const pctChg =
      preclose !== null && g.close !== null && preclose !== 0
        ? ((g.close - preclose) / preclose) * 100
        : null;
    prevClose = g.close;
    return { ...g, preclose, pctChg, turn: null };
  });
}
