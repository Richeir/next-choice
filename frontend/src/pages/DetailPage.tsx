import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  analyze,
  getEtfAnalysis,
  getEtfDetail,
  getJob,
  getKline,
  getStockAnalysis,
  getStockDetail,
} from '../api';
import type { AnalysisItem, EtfDetail, KlineItem, StockDetail } from '../api/types';
import StatusTag from '../components/StatusTag';
import RatingBadge from '../components/RatingBadge';
import KlineChart from '../components/KlineChart';
import { Empty, ErrorView, Loading } from '../components/StateViews';
import {
  displayCode,
  fmtAmountYi,
  fmtNum,
  fmtPct,
  pctClass,
  shortCode,
} from '../utils/format';
import { DEFAULT_KLINE_RANGE, KLINE_RANGES } from '../config';

type Kind = 'stock' | 'etf';

const SIGNAL_TEXT: Record<string, string> = {
  BUY: '买入',
  HOLD: '持有',
  SELL: '卖出',
};

interface Metric {
  label: string;
  value: string;
}

function AnalysisCard({ analysis }: { analysis: AnalysisItem }) {
  const signalText = SIGNAL_TEXT[analysis.signal] ?? analysis.signal;
  const paragraphs = [analysis.note, analysis.llmAnalysis].filter(
    (p): p is string => !!p,
  );
  return (
    <>
      <div className="analysis-section-label mono">{analysis.date} 收盘后生成</div>
      <div className="analysis-card">
        <RatingBadge rating={analysis.rating} score={analysis.score} />
        <div className="analysis-body">
          <h3>综合评分 · 建议：{signalText}</h3>
          {paragraphs.length > 0 ? (
            paragraphs.map((p, i) => <p key={i}>{p}</p>)
          ) : (
            <p>暂无分析摘要。</p>
          )}
        </div>
      </div>
    </>
  );
}

function MetricsRow({ metrics }: { metrics: Metric[] }) {
  return (
    <div className="metrics-row">
      {metrics.map((m) => (
        <div key={m.label} className="metric-cell">
          <div className="metric-label">{m.label}</div>
          <div className="metric-value">{m.value}</div>
        </div>
      ))}
    </div>
  );
}

function KlineSection({ kind, code }: { kind: Kind; code: string }) {
  const [range, setRange] = useState<string>(DEFAULT_KLINE_RANGE);
  const [kline, setKline] = useState<KlineItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const limit = KLINE_RANGES.find((r) => r.key === range)?.limit ?? 126;

  const load = useCallback(() => {
    setError(null);
    setKline(null);
    getKline(kind, code, { limit })
      .then(setKline)
      .catch((e: Error) => setError(e.message));
  }, [kind, code, limit]);

  useEffect(load, [load]);

  return (
    <div>
      <div className="kline-toolbar">
        <span>区间</span>
        <div className="range-selector">
          {KLINE_RANGES.map((r) => (
            <button
              key={r.key}
              className={`range-btn${r.key === range ? ' active' : ''}`}
              onClick={() => setRange(r.key)}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>
      <div className="kline-card">
        {error ? (
          <ErrorView message={error} onRetry={load} />
        ) : !kline ? (
          <Loading text="K 线加载中…" />
        ) : kline.length === 0 ? (
          <Empty text="暂无 K 线数据" />
        ) : (
          <KlineChart data={kline} />
        )}
      </div>
      <div className="kline-legend">
        <span>收盘价</span>
        <span>MA20</span>
        <span>MA60</span>
        <span>成交量（红跌绿涨）</span>
      </div>
    </div>
  );
}

const POLL_INTERVAL_MS = 1500;

export default function DetailPage({ kind }: { kind: Kind }) {
  const { code = '' } = useParams();
  const [detail, setDetail] = useState<StockDetail | EtfDetail | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisItem | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState<string | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    const detailReq =
      kind === 'stock' ? getStockDetail(code) : getEtfDetail(code);
    const analysisReq =
      kind === 'stock' ? getStockAnalysis(code) : getEtfAnalysis(code);
    Promise.all([detailReq, analysisReq.catch(() => null)])
      .then(([d, a]) => {
        setDetail(d);
        setAnalysis(a?.items?.[0] ?? null);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [kind, code]);

  useEffect(load, [load]);

  const pollUntilDone = useCallback(
    async (jobId: string) => {
      for (;;) {
        const job = await getJob(jobId);
        if (job.status === 'done' || job.status === 'failed') return job;
        await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
        // 组件已卸载时停止轮询，避免泄漏请求
        if (!mountedRef.current) return null;
      }
    },
    [],
  );

  const startAnalysis = useCallback(async () => {
    setAnalyzing(true);
    setAnalyzeError(null);
    try {
      const { jobId } = await analyze(kind, code);
      const job = await pollUntilDone(jobId);
      if (job?.status === 'failed') {
        setAnalyzeError(job.error || '分析失败，请稍后重试');
      }
    } catch (e: unknown) {
      if (!mountedRef.current) return;
      setAnalyzeError(e instanceof Error ? e.message : '分析失败，请稍后重试');
    } finally {
      if (!mountedRef.current) return;
      setAnalyzing(false);
      load();
    }
  }, [kind, code, load, pollUntilDone]);

  const view = useMemo(() => {
    if (!detail) return null;
    const isStock = kind === 'stock';
    const s = detail as StockDetail;
    const e = detail as EtfDetail;
    const price = isStock ? s.lastClose : (e.nav ?? e.lastClose);
    const pct = detail.lastPctChg;
    const desc = isStock
      ? [s.fullName ?? s.codeName, s.ipoDate ? `${s.ipoDate} 上市` : null,
         s.totalMarketCap != null ? `总市值 ${fmtAmountYi(s.totalMarketCap)}` : null]
        .filter(Boolean)
        .join(' · ')
      : [e.manager ?? '管理人 —', e.category ?? '类别 —', e.ipoDate ? `${e.ipoDate} 上市` : null]
        .filter(Boolean)
        .join(' · ');

    const metrics: Metric[] = isStock
      ? [
          { label: '成交额', value: fmtAmountYi(s.lastAmount) },
          { label: '换手率', value: '—' },
          { label: 'PE (TTM)', value: fmtNum(s.peTtm, 1) },
          { label: 'PB', value: fmtNum(s.pb, 1) },
          { label: '总市值', value: fmtAmountYi(s.totalMarketCap) },
          { label: '52 周高', value: fmtNum(s.high52w) },
          { label: '52 周低', value: fmtNum(s.low52w) },
        ]
      : [
          { label: '规模', value: fmtAmountYi(e.fundScale) },
          { label: '管理人', value: e.manager ?? '—' },
          { label: '类别', value: e.category ?? '—' },
          { label: '最新 NAV', value: fmtNum(e.nav ?? e.lastClose, 3) },
          { label: '日涨跌', value: fmtPct(e.lastPctChg) },
          { label: '52 周高', value: fmtNum(e.high52w) },
          { label: '52 周低', value: fmtNum(e.low52w) },
        ];

    return { isStock, price, pct, desc, metrics };
  }, [detail, kind]);

  if (loading) return <div className="page"><Loading /></div>;
  if (error)
    return (
      <div className="page">
        <ErrorView message={error} onRetry={load} />
      </div>
    );
  if (!detail || !view) return <div className="page"><Empty text="未找到该标的" /></div>;

  const crumbType = view.isStock ? '股票' : 'ETF';
  const crumbMid = view.isStock
    ? (detail as StockDetail).industry
    : (detail as EtfDetail).category;

  return (
    <div className="page">
      <div className="breadcrumb">
        <Link to={view.isStock ? '/stocks' : '/etfs'}>{crumbType}</Link>
        <span className="sep">/</span>
        {crumbMid ?? '—'}
        <span className="sep">/</span>
        {shortCode(detail.code)}
      </div>

      <div className="detail-head">
        <div>
          <div className="detail-code-row">
            <span className="detail-code">{displayCode(detail.code)}</span>
            <StatusTag analyzed={!!analysis} />
          </div>
          <h1 className="detail-name">{detail.codeName}</h1>
          <div className="detail-desc">{view.desc}</div>
        </div>
        <div className="detail-price-box">
          <div className="detail-price">{fmtNum(view.price, view.isStock ? 2 : 3)}</div>
          <div className={`detail-chg ${pctClass(view.pct)}`}>{fmtPct(view.pct)}</div>
          <div className="detail-time mono">
            {detail.lastTradeDate ? `${detail.lastTradeDate} 收盘 · 15:00 CST` : '—'}
          </div>
        </div>
      </div>

      {analysis ? (
        <AnalysisCard analysis={analysis} />
      ) : (
        <div className="analysis-section-label">暂无分析结果</div>
      )}

      <div className="analyze-row">
        <button
          className="btn-analyze"
          onClick={startAnalysis}
          disabled={analyzing}
        >
          {analyzing ? '分析中…' : '开始分析'}
        </button>
        {analyzeError && <span className="analyze-error">{analyzeError}</span>}
      </div>

      <MetricsRow metrics={view.metrics} />

      <KlineSection kind={kind} code={code} />
    </div>
  );
}
