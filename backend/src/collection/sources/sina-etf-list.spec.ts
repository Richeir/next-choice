import { makeMockFetch } from '../testing/mock-fetch';
import { listEtfs } from './sina-etf-list';

// 壳格式取自真实响应存档（剥壳后为标准 JSON 数组，键带引号）
const wrapper = (payload: string) =>
  `/*<script>location.href='//sina.com';</script>*/\n` +
  `IO.XSRV2.CallbackList['da_yPT46_Ll7K6WD'](${payload})`;

describe('listEtfs', () => {
  test('strips jsonp shell and maps prefix to market', async () => {
    const fetchImpl = makeMockFetch([
      {
        match: (url) => url.includes('getHQNodeDataSimple') && url.includes('etf_hq_fund'),
        body: wrapper(
          JSON.stringify([
            { symbol: 'sz159998', name: '计算机ETF天弘' },
            { symbol: 'sh510050', name: '50ETF' },
            { symbol: '500999', name: '无前缀兜底' },
          ]),
        ),
      },
    ]);
    const items = await listEtfs({ fetchImpl });
    expect(items).toEqual([
      { code: '159998', name: '计算机ETF天弘', market: 'SZ' },
      { code: '510050', name: '50ETF', market: 'SH' },
      { code: '500999', name: '无前缀兜底', market: null },
    ]);
  });

  test('empty array surfaces fatal error (list must not silently degrade)', async () => {
    const fetchImpl = makeMockFetch([
      { match: () => true, body: wrapper(JSON.stringify([])) },
    ]);
    await expect(listEtfs({ fetchImpl })).rejects.toThrow(/empty/i);
  });

  test('malformed shell throws instead of parsing garbage', async () => {
    const fetchImpl = makeMockFetch([{ match: () => true, body: 'not jsonp' }]);
    await expect(listEtfs({ fetchImpl })).rejects.toThrow(/malformed/);
  });
});
