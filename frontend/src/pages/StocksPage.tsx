import { getStocks } from '../api';
import type { StockListItem } from '../api/types';
import SecurityListPage, {
  ratingColumn,
  type SecurityListConfig,
} from '../components/SecurityListPage';
import { fmtAmountYi, fmtNum, fmtPct, pctClass } from '../utils/format';

const SORT_OPTIONS = [
  { value: 'code', label: '代码' },
  { value: 'lastClose', label: '最新' },
  { value: 'lastPctChg', label: '涨跌' },
  { value: 'lastAmount', label: '成交额' },
  { value: 'peTtm', label: 'PE' },
  { value: 'rating', label: '评级' },
];

const config: SecurityListConfig<StockListItem> = {
  breadcrumbLabel: '股票',
  titlePrefix: '股票列表',
  description:
    '已覆盖沪深京三地主要标的，点击代码查看个股详情。支持按市场、行业、状态筛选与多维排序。',
  emptyText: '没有符合条件的股票',
  routeBase: '/stocks',
  fetcher: getStocks,
  analyzedCountOf: (s) => s.stockAnalyzedCnt,
  sortOptions: SORT_OPTIONS,
  staticFields: [
    { key: 'keyword', label: '搜索', type: 'search', placeholder: '代码 / 名称' },
    {
      key: 'market',
      label: '市场',
      type: 'select',
      options: [
        { value: '', label: '全部' },
        { value: 'SH', label: 'SH' },
        { value: 'SZ', label: 'SZ' },
      ],
    },
  ],
  dynamicFilters: [{ key: 'industry', label: '行业', pick: (it) => it.industry }],
  columns: [
    {
      key: 'name',
      header: '名称 / 行业',
      render: (it) => (
        <>
          <div className="cell-name">{it.codeName}</div>
          <div className="cell-sub">{it.industry ?? '—'}</div>
        </>
      ),
    },
    ratingColumn<StockListItem>((it) => it.analysis?.rating ?? null),
    { key: 'lastClose', header: '最新', numeric: true, render: (it) => fmtNum(it.lastClose) },
    {
      key: 'lastPctChg',
      header: '涨跌',
      numeric: true,
      cellClass: (it) => pctClass(it.lastPctChg),
      render: (it) => fmtPct(it.lastPctChg),
    },
    {
      key: 'lastAmount',
      header: '成交额',
      numeric: true,
      render: (it) => fmtAmountYi(it.lastAmount),
    },
    { key: 'peTtm', header: 'PE', numeric: true, render: (it) => fmtNum(it.peTtm, 1) },
  ],
  hasAnalysis: (it) => !!it.analysis,
  codeOf: (it) => it.code,
};

export default function StocksPage() {
  return <SecurityListPage config={config} />;
}
