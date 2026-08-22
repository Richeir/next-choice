import { toCamel, rowToCamel } from './mapper';

describe('mapper', () => {
  it('toCamel 转换 snake_case', () => {
    expect(toCamel('last_trade_date')).toBe('lastTradeDate');
    expect(toCamel('code')).toBe('code');
    expect(toCamel('is_worth_buying')).toBe('isWorthBuying');
  });

  it('rowToCamel 映射整行并保留 null', () => {
    const row = {
      code: '600000',
      last_trade_date: '2024-01-31',
      high_52w: null,
      last_close: 6.83,
    };
    expect(rowToCamel(row)).toEqual({
      code: '600000',
      lastTradeDate: '2024-01-31',
      high52w: null,
      lastClose: 6.83,
    });
  });
});
