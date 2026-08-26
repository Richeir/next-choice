import {
  marketOf,
  numOrNull,
  stripPrefix,
  toSinaCode,
  toXqCode,
  wanToYuan,
  yiToYuan,
} from './codes';

describe('codes', () => {
  describe('marketOf', () => {
    test.each([
      ['600000', 'SH'],
      ['688808', 'SH'],
      ['510050', 'SH'],
      ['588660', 'SH'],
      ['000001', 'SZ'],
      ['300750', 'SZ'],
      ['159998', 'SZ'],
    ])('%s -> %s', (code, market) => {
      expect(marketOf(code)).toBe(market);
    });

    test('unknown segment throws', () => {
      expect(() => marketOf('999999')).toThrow(/unknown code segment/);
    });
  });

  test('code format converters', () => {
    expect(toSinaCode('600000')).toBe('sh600000');
    expect(toXqCode('600000')).toBe('SH600000');
    expect(stripPrefix('sz159998')).toBe('159998');
  });

  describe('numOrNull', () => {
    test.each([
      [null, null],
      [undefined, null],
      ['', null],
      ['-', null],
      ['abc', null],
      [Number.NaN, null],
      ['338.95', 338.95],
      [-12.99, -12.99],
      [0, 0],
    ])('%p -> %p', (input, expected) => {
      expect(numOrNull(input)).toBe(expected);
    });
  });

  test('unit conversions scale by 1e8 / 1e4 with dirty passthrough', () => {
    expect(yiToYuan('2319.24')).toBeCloseTo(231924000000);
    expect(wanToYuan('150207')).toBe(1502070000);
    expect(yiToYuan('-')).toBeNull();
    expect(wanToYuan(null)).toBeNull();
  });
});
