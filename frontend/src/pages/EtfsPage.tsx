import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { getEtfs, getStats } from '../api';
import type { EtfListItem } from '../api/types';
import { useListPage } from '../hooks/useListPage';
import FilterBar, { type FilterField } from '../components/FilterBar';
import Pagination from '../components/Pagination';
import StatusTag from '../components/StatusTag';
import RatingTag from '../components/RatingTag';
import { Empty, ErrorView, Loading } from '../components/StateViews';
import { fmtAmountYi, fmtInt, fmtNum, fmtPct, pctClass, shortCode } from '../utils/format';
import { PAGE_SIZE } from '../config';

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

export default function EtfsPage() {
  const [filters, setFilters] = useState<Record<string, string>>({
    keyword: '',
    category: '',
    market: '',
    manager: '',
    sortBy: 'code',
  });
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(PAGE_SIZE);
  const [managers, setManagers] = useState<string[]>([]);
  const [analyzedTotal, setAnalyzedTotal] = useState<number | null>(null);

  useEffect(() => {
    getStats()
      .then((s) => setAnalyzedTotal(s.analyzedCnt))
      .catch(() => setAnalyzedTotal(null));
  }, []);

  const params = useMemo(
    () => ({
      keyword: filters.keyword || undefined,
      category: filters.category || undefined,
      market: filters.market || undefined,
      manager: filters.manager || undefined,
      sortBy: filters.sortBy || 'code',
      order: 'desc',
      page,
      pageSize,
    }),
    [filters, page, pageSize],
  );

  const { data, loading, error, reload } = useListPage<EtfListItem>(getEtfs, params);

  // 管理人选项从已加载数据累积（后端无管理人字典接口）
  useEffect(() => {
    if (!data) return;
    setManagers((prev) => {
      const next = new Set(prev);
      data.items.forEach((it) => it.manager && next.add(it.manager));
      return next.size === prev.length ? prev : [...next].sort();
    });
  }, [data]);

  const onFilterChange = useCallback((key: string, value: string) => {
    setFilters((f) => ({ ...f, [key]: value }));
    setPage(1);
  }, []);

  const fields: FilterField[] = [
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
    {
      key: 'manager',
      label: '管理人',
      type: 'select',
      options: [{ value: '', label: '全部' }, ...managers.map((v) => ({ value: v, label: v }))],
    },
    { key: 'sortBy', label: '排序', type: 'select', options: SORT_OPTIONS },
  ];

  return (
    <div className="page">
      <div className="breadcrumb">
        — 系统数据 <span className="sep">/</span> ETF
      </div>
      <h1 className="page-title">
        ETF 列表 · {analyzedTotal === null ? '—' : fmtInt(analyzedTotal)} 已分析
      </h1>
      <p className="page-desc">
        覆盖宽基、行业、主题、债券与跨境 ETF，完成折溢价跟踪。点击代码查看 ETF 详情。
      </p>

      <FilterBar
        fields={fields}
        values={filters}
        total={data?.total ?? 0}
        onChange={onFilterChange}
      />

      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorView message={error} onRetry={reload} />
      ) : !data || data.items.length === 0 ? (
        <Empty text="没有符合条件的 ETF" />
      ) : (
        <>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>代码</th>
                  <th>名称 / 管理人</th>
                  <th>评级</th>
                  <th>类别</th>
                  <th className="num">最新 NAV</th>
                  <th className="num">日涨跌</th>
                  <th className="num">规模</th>
                  <th>状态</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((it) => {
                  const nav = it.nav ?? it.lastClose;
                  return (
                    <tr key={it.code}>
                      <td className="cell-code">{shortCode(it.code)}</td>
                      <td>
                        <div className="cell-name">{it.codeName}</div>
                        <div className="cell-sub">{it.manager ?? '—'}</div>
                      </td>
                      <td>
                        <RatingTag rating={it.analysis?.rating ?? null} />
                      </td>
                      <td>
                        {it.category ? (
                          <span className="tag category">{it.category}</span>
                        ) : (
                          '—'
                        )}
                      </td>
                      <td className="num mono">{fmtNum(nav, 3)}</td>
                      <td className={`num mono ${pctClass(it.lastPctChg)}`}>
                        {fmtPct(it.lastPctChg)}
                      </td>
                      <td className="num mono">{fmtAmountYi(it.fundScale)}</td>
                      <td>
                        <StatusTag analyzed={!!it.analysis} />
                      </td>
                      <td>
                        <Link to={`/etfs/${it.code}`}>
                          <button className="btn-view">查看</button>
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <Pagination
            page={page}
            pageSize={pageSize}
            total={data?.total ?? 0}
            onPageChange={setPage}
            onPageSizeChange={(n) => {
              setPageSize(n);
              setPage(1);
            }}
          />
        </>
      )}
    </div>
  );
}
