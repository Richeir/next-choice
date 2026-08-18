import { useCallback, useEffect, useState } from 'react';
import { getStats } from '../api';
import type { Stats } from '../api/types';
import { fmtInt, fmtNum } from '../utils/format';
import { Empty, ErrorView, Loading } from '../components/StateViews';

function StatCard({
  title,
  total,
  analyzed,
}: {
  title: string;
  total: number;
  analyzed: number;
}) {
  const pct = total > 0 ? Math.min(100, (analyzed / total) * 100) : 0;
  return (
    <div className="stat-card">
      <div className="stat-card-title">{title}</div>
      <div className="stat-card-number mono">{fmtInt(total)}</div>
      <div className="stat-card-row">
        <span className="stat-card-analyzed">
          已分析<b className="mono">{fmtInt(analyzed)}</b>
        </span>
        <span className="pct-pill mono">{fmtNum(pct, 1)}%</span>
      </div>
      <div className="progress-track">
        <div className="progress-fill" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export default function HomePage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    getStats()
      .then(setStats)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  return (
    <div className="page">
      <div className="breadcrumb">— 系统数据</div>
      <h1 className="page-title">股票 / ETF 数据汇总</h1>
      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorView message={error} onRetry={load} />
      ) : !stats ? (
        <Empty />
      ) : (
        <div className="stat-cards">
          <StatCard title="股票 · STOCKS" total={stats.stockCnt} analyzed={stats.analyzedCnt} />
          <StatCard title="ETF · 交易所基金" total={stats.etfCnt} analyzed={stats.analyzedCnt} />
        </div>
      )}
    </div>
  );
}
