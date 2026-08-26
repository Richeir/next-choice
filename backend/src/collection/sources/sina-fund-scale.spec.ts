import { makeMockFetch } from '../testing/mock-fetch';
import { fundScaleMap } from './sina-fund-scale';

const wrapper = (obj: object) =>
  "/*<script>location.href='//sina.com';</script>*/\n" +
  "IO.XSRV2.CallbackList['J2cW8KXheoWKdSHc'](" +
  JSON.stringify(obj) +
  ')';

describe('fundScaleMap', () => {
  test('keys by stringified numeric symbol and converts 万 -> 元', async () => {
    const fetchImpl = makeMockFetch([
      {
        match: (url) => url.includes('NetValueReturnOpen') && url.includes('type2=2'),
        body: wrapper({
          total_num: 6919,
          data: [
            { symbol: 510300, zmjgm: '329686.00', jjjl: '张三', clrq: '2004-04-08' },
            { symbol: '159998', zmjgm: null, jjjl: null, clrq: '' },
          ],
        }),
      },
    ]);
    const map = await fundScaleMap({ fetchImpl });
    // 注意：JS 对象的纯数字键按数值升序遍历，不保证插入序，只断言集合与值
    expect(Object.keys(map).sort()).toEqual(['159998', '510300'].sort());
    expect(map['510300']).toEqual({
      fund_scale: 3296860000, // 万 -> 元
      manager: '张三',
      ipo_date: '2004-04-08',
    });
    // 脏值透传 null，与 Python None 语义一致
    expect(map['159998']).toEqual({ fund_scale: null, manager: null, ipo_date: null });
  });

  test('empty data throws fatal error', async () => {
    const fetchImpl = makeMockFetch([
      { match: () => true, body: wrapper({ total_num: 0, data: [] }) },
    ]);
    await expect(fundScaleMap({ fetchImpl })).rejects.toThrow(/empty/);
  });
});
