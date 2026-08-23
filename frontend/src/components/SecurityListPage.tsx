import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { getStats } from '../api';
import type { ListParams, Paged, Stats } from '../api/types';
import { useListPage } from '../hooks/useListPage';
import FilterBar, { type FilterField } from './FilterBar';
import Pagination from './Pagination';
import StatusTag from './StatusTag';
import RatingTag from './RatingTag';
import { Empty, ErrorView, Loading } from './StateViews';
import { fmtInt, shortCode } from '../utils/format';
import { PAGE_SIZE } from '../config';

/** 证券列表页中间部分的列（代码 / 状态 / 操作三列由组件固定提供）。 */
export interface ListColumn<T> {
  key: string;
  header: string;
  /** 数字列右对齐 */
  numeric?: boolean;
  /** 追加到单元格的类名，如涨跌的红绿 */
  cellClass?: (item: T) => string;
  render: (item: T) => ReactNode;
}

/** 选项无字典接口，从已加载数据里累积的筛选项（行业 / 管理人）。 */
export interface DynamicFilter<T> {
  key: string;
  label: string;
  pick: (item: T) => string | null | undefined;
}

export interface SecurityListConfig<T> {
  breadcrumbLabel: string;
  titlePrefix: string;
  description: string;
  emptyText: string;
  /** 详情页路由前缀，如 /stocks */
  routeBase: string;
  fetcher: (params: ListParams) => Promise<Paged<T>>;
  /** 该品种的已分析标的数（股票与 ETF 各取各的，不能用合计） */
  analyzedCountOf: (stats: Stats) => number;
  sortOptions: { value: string; label: string }[];
  staticFields: FilterField[];
  dynamicFilters?: DynamicFilter<T>[];
  columns: ListColumn<T>[];
  hasAnalysis: (item: T) => boolean;
  codeOf: (item: T) => string;
}

const ANALYSIS_STATUS_OPTIONS = [
  { value: '', label: '全部' },
  { value: 'analyzed', label: '已分析' },
  { value: 'pending', label: '待分析' },
];

/**
 * 股票 / ETF 列表页的通用实现：筛选 + 排序 + 分页 + 表格。
 * 两个品种只在列定义、筛选项和取数函数上不同，由 config 注入。
 */
export default function SecurityListPage<T>({ config }: { config: SecurityListConfig<T> }) {
  const {
    breadcrumbLabel,
    titlePrefix,
    description,
    emptyText,
    routeBase,
    fetcher,
    analyzedCountOf,
    sortOptions,
    staticFields,
    dynamicFilters,
    columns,
    hasAnalysis,
    codeOf,
  } = config;

  const [filters, setFilters] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = { analysisStatus: '', sortBy: 'code' };
    staticFields.forEach((f) => (init[f.key] = ''));
    dynamicFilters?.forEach((f) => (init[f.key] = ''));
    return init;
  });
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(PAGE_SIZE);
  const [dynamicOptions, setDynamicOptions] = useState<Record<string, string[]>>({});
  const [analyzedTotal, setAnalyzedTotal] = useState<number | null>(null);

  useEffect(() => {
    getStats()
      .then((s) => setAnalyzedTotal(analyzedCountOf(s)))
      .catch(() => setAnalyzedTotal(null));
  }, [analyzedCountOf]);

  const params = useMemo(() => {
    const p: ListParams = {
      sortBy: filters.sortBy || 'code',
      order: 'desc',
      page,
      pageSize,
    };
    for (const [key, value] of Object.entries(filters)) {
      if (key !== 'sortBy' && value) p[key] = value;
    }
    return p;
  }, [filters, page, pageSize]);

  const { data, loading, error, reload } = useListPage<T>(fetcher, params);

  // 选项从已加载数据累积（后端无行业/管理人字典接口）
  useEffect(() => {
    if (!data || !dynamicFilters?.length) return;
    setDynamicOptions((prev) => {
      let changed = false;
      const next = { ...prev };
      for (const f of dynamicFilters) {
        const set = new Set(prev[f.key] ?? []);
        const before = set.size;
        data.items.forEach((it) => {
          const v = f.pick(it);
          if (v) set.add(v);
        });
        if (set.size !== before) {
          next[f.key] = [...set].sort();
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [data, dynamicFilters]);

  const onFilterChange = useCallback((key: string, value: string) => {
    setFilters((f) => ({ ...f, [key]: value }));
    setPage(1);
  }, []);

  const fields: FilterField[] = useMemo(
    () => [
      ...staticFields,
      ...(dynamicFilters ?? []).map((f) => ({
        key: f.key,
        label: f.label,
        type: 'select' as const,
        options: [
          { value: '', label: '全部' },
          ...(dynamicOptions[f.key] ?? []).map((v) => ({ value: v, label: v })),
        ],
      })),
      {
        key: 'analysisStatus',
        label: '状态',
        type: 'select',
        options: ANALYSIS_STATUS_OPTIONS,
      },
      { key: 'sortBy', label: '排序', type: 'select', options: sortOptions },
    ],
    [staticFields, dynamicFilters, dynamicOptions, sortOptions],
  );

  return (
    <div className="page">
      <div className="breadcrumb">
        — 系统数据 <span className="sep">/</span> {breadcrumbLabel}
      </div>
      <h1 className="page-title">
        {titlePrefix} · {analyzedTotal === null ? '—' : fmtInt(analyzedTotal)} 已分析
      </h1>
      <p className="page-desc">{description}</p>

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
        <Empty text={emptyText} />
      ) : (
        <>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>代码</th>
                  {columns.map((c) => (
                    <th key={c.key} className={c.numeric ? 'num' : undefined}>
                      {c.header}
                    </th>
                  ))}
                  <th>状态</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((it) => {
                  const code = codeOf(it);
                  return (
                    <tr key={code}>
                      <td className="cell-code">{shortCode(code)}</td>
                      {columns.map((c) => (
                        <td
                          key={c.key}
                          className={
                            [c.numeric ? 'num mono' : '', c.cellClass?.(it) ?? '']
                              .filter(Boolean)
                              .join(' ') || undefined
                          }
                        >
                          {c.render(it)}
                        </td>
                      ))}
                      <td>
                        <StatusTag analyzed={hasAnalysis(it)} />
                      </td>
                      <td>
                        <Link className="btn-view" to={`${routeBase}/${code}`}>
                          查看
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

/** 评级列在两个品种上完全一致，作为便捷渲染器复用。 */
export function ratingColumn<T>(ratingOf: (item: T) => string | null): ListColumn<T> {
  return {
    key: 'rating',
    header: '评级',
    render: (it) => <RatingTag rating={ratingOf(it)} />,
  };
}
