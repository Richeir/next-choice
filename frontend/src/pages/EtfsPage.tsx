import { getEtfs } from '../api';
import type { EtfListItem } from '../api/types';
import SecurityListPage, {
  ratingColumn,
  type SecurityListConfig,
} from '../components/SecurityListPage';
import { fmtAmountYi, fmtNum, fmtPct, pctClass } from '../utils/format';

const SORT_OPTIONS = [
  { value: 'code', label: '代码' },
  { value: 'nav', label: '最新 NAV' },
  { value: 'lastPctChg', label: '日涨跌' },
  { value: 'fundScale', label: '规模' },
  { value: 'rating', label: '评级' },
];

const CATEGORY_OPTIONS = [
  { value: '', label: '全部' },
  { value: '宽基', label: '宽基' },
  { value: '行业', label: '行业' },
  { value: '策略', label: '策略' },
  { value: '跨境', label: '跨境' },
  { value: '债券', label: '债券' },
];

const config: SecurityListConfig<EtfListItem> = {
  breadcrumbLabel: 'ETF',
  titlePrefix: 'ETF 列表',
  description:
    '覆盖宽基、行业、主题、债券与跨境 ETF，完成折溢价跟踪。点击代码查看 ETF 详情。',
  emptyText: '没有符合条件的 ETF',
  routeBase: '/etfs',
  fetcher: getEtfs,
  analyzedCountOf: (s) => s.etfAnalyzedCnt,
  sortOptions: SORT_OPTIONS,
  staticFields: [
    { key: 'keyword', label: '搜索', type: 'search', placeholder: '代码 / 名称' },
    { key: 'category', label: '类别', type: 'select', options: CATEGORY_OPTIONS },
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
  dynamicFilters: [{ key: 'manager', label: '管理人', pick: (it) => it.manager }],
  columns: [
    {
      key: 'name',
      header: '名称 / 管理人',
      render: (it) => (
        <>
          <div className="cell-name">{it.codeName}</div>
          <div className="cell-sub">{it.manager ?? '—'}</div>
        </>
      ),
    },
    ratingColumn<EtfListItem>((it) => it.analysis?.rating ?? null),
    {
      key: 'category',
      header: '类别',
      render: (it) =>
        it.category ? <span className="tag category">{it.category}</span> : '—',
    },
    {
      key: 'nav',
      header: '最新 NAV',
      numeric: true,
      render: (it) => fmtNum(it.nav ?? it.lastClose, 3),
    },
    {
      key: 'lastPctChg',
      header: '日涨跌',
      numeric: true,
      cellClass: (it) => pctClass(it.lastPctChg),
      render: (it) => fmtPct(it.lastPctChg),
    },
    {
      key: 'fundScale',
      header: '规模',
      numeric: true,
      render: (it) => fmtAmountYi(it.fundScale),
    },
  ],
  hasAnalysis: (it) => !!it.analysis,
  codeOf: (it) => it.code,
};

export default function EtfsPage() {
  return <SecurityListPage config={config} />;
}
