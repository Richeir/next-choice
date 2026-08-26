import { KlineRow } from './normalize';
import { resampleKline } from './resample';

const row = (date: string, close: number, volume = 100): KlineRow => ({
  date,
  open: close - 1,
  high: close + 2,
  low: close - 3,
  close,
  preclose: null,
  volume,
  amount: volume * 10,
  turn: 0.5,
  pctChg: null,
});

describe('resampleKline', () => {
  test('weekly groups run Monday through Sunday', () => {
    // 2026-08-24（周一）~ 2026-08-30（周日）
    const rows = [
      row('2026-08-24', 9.22, 100),
      row('2026-08-26', 9.21, 300),
      row('2026-08-31', 9.5, 400), // 下周一
    ];
    const weekly = resampleKline(rows, 'weekly');
    expect(weekly).toHaveLength(2);
    expect(weekly[0]).toMatchObject({
      date: '2026-08-26',
      open: 8.22, // 组内第一根的 open
      close: 9.21,
      volume: 400,
      amount: 4000,
      turn: null, // 周线不换算换手
    });
    expect(weekly[0].high).toBeCloseTo(11.22); // max(close+2)
    expect(weekly[0].low).toBeCloseTo(6.21); // min(close-3)
    expect(weekly[0].preclose).toBeNull();
    expect(weekly[1].preclose).toBeCloseTo(9.21);
    expect(weekly[1].pctChg).toBeCloseTo(((9.5 - 9.21) / 9.21) * 100);
  });

  test('monthly groups by calendar month and chains preclose across months', () => {
    const rows = [row('2026-07-31', 10), row('2026-08-03', 11), row('2026-08-29', 12)];
    const monthly = resampleKline(rows, 'monthly');
    expect(monthly.map((r) => r.date)).toEqual(['2026-07-31', '2026-08-29']);
    expect(monthly[1].open).toBe(10); // 8 月组首根 (08-03) 的 open = close-1
    expect(monthly[1].close).toBe(12);
    expect(monthly[1].preclose).toBe(10);
  });

  test('invalid freq throws like python ValueError', () => {
    expect(() => resampleKline([], 'daily' as never)).toThrow(
      /resample freq must be weekly\/monthly/,
    );
  });
});
