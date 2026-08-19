import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { getStats, getStocks } from '../api';
import type { StockListItem } from '../api/types';
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
  { value: 'lastClose', label: '最新' },
  { value: 'lastPctChg', label: '涨跌' },
  { value: 'lastAmount', label: '成交额' },
  { value: 'peTtm', label: 'PE' },
  { value: 'rating', label: '评级' },
];

export default function StocksPage() {
  const [filters, setFilters] = useState<Record<string, string>>({
    keyword: '',
    market: '',
    industry: '',
    status: '',
    sortBy: 'code',
  });
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(PAGE_SIZE);
  const [industries, setIndustries] = useState<string[]>([]);
  const [analyzedTotal, setAnalyzedTotal] = useState<number | null>(null);

  useEffect(() => {
    getStats()
      .then((s) => setAnalyzedTotal(s.analyzedCnt))
      .catch(() => setAnalyzedTotal(null));
  }, []);

  const params = useMemo(
    () => ({
      keyword: filters.keyword || undefined,
      market: filters.market || undefined,
      industry: filters.industry || undefined,
      sortBy: filters.sortBy || 'code',
      order: 'desc',
      page,
      pageSize,
    }),
    [filters, page, pageSize],
  );

  const { data, loading, error, reload } = useListPage<StockListItem>(getStocks, params);

  // 行业选项从已加载数据累积（后端无行业字典接口）
  useEffect(() => {
    if (!data) return;
    setIndustries((prev) => {
      const next = new Set(prev);
      data.items.forEach((it) => it.industry && next.add(it.industry));
      return next.size === prev.length ? prev : [...next].sort();
    });
  }, [data]);

  const onFilterChange = useCallback((key: string, value: string) => {
    setFilters((f) => ({ ...f, [key]: value }));
    setPage(1);
  }, []);

  // “已分析/待分析”后端暂不支持，按当前页客户端过滤
  const items = useMemo(() => {
    if (!data) return [];
    if (filters.status === 'analyzed') return data.items.filter((it) => it.analysis);
    if (filters.status === 'pending') return data.items.filter((it) => !it.analysis);
    return data.items;
  }, [data, filters.status]);


  const fields: FilterField[] = [
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
    {
      key: 'industry',
      label: '行业',
      type: 'select',
      options: [{ value: '', label: '全部' }, ...industries.map((v) => ({ value: v, label: v }))],
    },
    {
      key: 'status',
      label: '状态',
      type: 'select',
      options: [
        { value: '', label: '全部' },
        { value: 'analyzed', label: '已分析' },
        { value: 'pending', label: '待分析' },
      ],
    },
    { key: 'sortBy', label: '排序', type: 'select', options: SORT_OPTIONS },
  ];

  return (
    <div className="page">
      <div className="breadcrumb">
        — 系统数据 <span className="sep">/</span> 股票
      </div>
      <h1 className="page-title">
        股票列表 · {analyzedTotal === null ? '—' : fmtInt(analyzedTotal)} 已分析
      </h1>
      <p className="page-desc">
        已覆盖沪深京三地主要标的，点击代码查看个股详情。支持按市场、行业、状态筛选与多维排序。
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
      ) : items.length === 0 ? (
        <Empty text="没有符合条件的股票" />
      ) : (
        <>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>代码</th>
                  <th>名称 / 行业</th>
                  <th>评级</th>
                  <th className="num">最新</th>
                  <th className="num">涨跌</th>
                  <th className="num">成交额</th>
                  <th className="num">PE</th>
                  <th>状态</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {items.map((it) => (
                  <tr key={it.code}>
                    <td className="cell-code">{shortCode(it.code)}</td>
                    <td>
                      <div className="cell-name">{it.codeName}</div>
                      <div className="cell-sub">{it.industry ?? '—'}</div>
                    </td>
                    <td>
                      <RatingTag rating={it.analysis?.rating ?? null} />
                    </td>
                    <td className="num mono">{fmtNum(it.lastClose)}</td>
                    <td className={`num mono ${pctClass(it.lastPctChg)}`}>
                      {fmtPct(it.lastPctChg)}
                    </td>
                    <td className="num mono">{fmtAmountYi(it.lastAmount)}</td>
                    <td className="num mono">{fmtNum(it.peTtm, 1)}</td>
                    <td>
                      <StatusTag analyzed={!!it.analysis} />
                    </td>
                    <td>
                      <Link to={`/stocks/${it.code}`}>
                        <button className="btn-view">查看</button>
                      </Link>
                    </td>
                  </tr>
                ))}
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
