import { readFixture } from './testing/mock-fetch';
import { decodeSinaKlines } from './sina-decrypt';
import { EmptyDataError } from './errors';

/**
 * 回归基线：fixture 为真实线上响应存档，预期值经 Python akshare
 * （py_mini_racer 执行同一解密函数）交叉验证一致。
 */
describe('decodeSinaKlines', () => {
  test('sh688808 fixture decodes to pinned oracle values', () => {
    const rows = decodeSinaKlines(readFixture('sina-kline-sh688808.js'));
    expect(rows).toHaveLength(85);
    expect(rows[0]).toMatchObject({
      date: '2026-04-24',
      open: 736.92,
      high: 859.88,
      low: 688.99,
      close: 799,
      volume: 15178530,
      amount: 11413259860,
      prevclose: 81.88,
    });
    expect(rows[rows.length - 1]).toEqual({
      date: '2026-08-26',
      open: 2219,
      high: 2274.44,
      low: 2123,
      close: 2259,
      volume: 677961,
      amount: 1502068235,
      prevclose: null,
    });
  });

  test('sh510050 fixture (etf) decodes to pinned oracle values', () => {
    const rows = decodeSinaKlines(readFixture('sina-kline-sh510050.js'));
    expect(rows).toHaveLength(5229);
    expect(rows[0]).toMatchObject({
      date: '2005-02-23',
      open: 0.881,
      high: 0.882,
      low: 0.866,
      close: 0.876,
      volume: 1269742542,
      amount: 1111793167,
      prevclose: 0.887,
    });
    expect(rows[rows.length - 1]).toEqual({
      date: '2026-08-26',
      open: 2.982,
      high: 3.026,
      low: 2.979,
      close: 3.013,
      volume: 900314519,
      amount: 2710243189,
      prevclose: null,
    });
  });

  test('missing payload throws EmptyDataError', () => {
    expect(() => decodeSinaKlines('no payload here')).toThrow(EmptyDataError);
  });

  test('empty decode result throws EmptyDataError', () => {
    // 合法壳但空密文：解码器返回空数组
    expect(() =>
      decodeSinaKlines('var KLC_K2_x="";'),
    ).toThrow(EmptyDataError);
  });
});
