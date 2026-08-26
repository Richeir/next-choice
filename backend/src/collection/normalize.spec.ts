import { normalizeDaily } from './normalize';
import { DecodedBar } from './sina-decrypt';

const bar = (over: Partial<DecodedBar>): DecodedBar => ({
  date: '2026-08-25',
  open: 10,
  high: 11,
  low: 9,
  close: 10.5,
  volume: 1000,
  amount: 10500,
  prevclose: null,
  ...over,
});

describe('normalizeDaily', () => {
  test('stock mode: preclose shifts from previous close, pctChg derived', () => {
    const rows = normalizeDaily([
      bar({ date: '2026-08-26', close: 11.55 }),
      bar({ date: '2026-08-25' }),
    ]);
    expect(rows.map((r) => r.date)).toEqual(['2026-08-25', '2026-08-26']);
    expect(rows[0].preclose).toBeNull();
    expect(rows[0].pctChg).toBeNull();
    expect(rows[1].preclose).toBe(10.5);
    expect(rows[1].pctChg).toBeCloseTo(((11.55 - 10.5) / 10.5) * 100);
    // 股票路径的 preclose 来自 shift(1)，与解密自带 prevclose 无关：
    // 上例首行解码 prevclose 为 null，若误用该列会得到 null 而非上一根收盘
  });

  test('etf mode: decoded preclose used verbatim including null', () => {
    const rows = normalizeDaily(
      [bar({ date: '2026-08-26', close: 3.013 }), bar({ date: '2026-08-25' })],
      { useDecodedPreclose: true },
    );
    expect(rows[0].preclose).toBeNull();
    expect(rows[1].preclose).toBeNull();
    expect(rows[1].pctChg).toBeNull();

    const withPrev = normalizeDaily([bar({ prevclose: 0.887 })], {
      useDecodedPreclose: true,
    });
    expect(withPrev[0].preclose).toBe(0.887);
    expect(withPrev[0].pctChg).toBeCloseTo(((10.5 - 0.887) / 0.887) * 100);
  });

  test('turn resolved via turnAt resolver; null when absent', () => {
    const rows = normalizeDaily([
      bar({ date: '2026-04-24', volume: 15178530 }),
      bar({ date: '1999-01-01', volume: 500 }),
    ], {
      turnAt: (date) =>
        date >= '2026-04-24' ? 19296144 : null,
    });
    expect(rows[1].turn).toBeCloseTo(0.7866094904764392, 12);
    expect(rows[0].turn).toBeNull();
  });

  test('input order does not matter (sorted by date)', () => {
    const rows = normalizeDaily([
      bar({ date: '2026-08-27', close: 12 }),
      bar({ date: '2026-08-26', close: 11.55 }),
    ]);
    expect(rows[0].date).toBe('2026-08-26');
    expect(rows[1].preclose).toBe(11.55);
  });
});
