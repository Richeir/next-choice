import { describe, expect, it, vi, beforeEach } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import HomePage from '../pages/HomePage';
import StocksPage from '../pages/StocksPage';
import EtfsPage from '../pages/EtfsPage';
import DetailPage from '../pages/DetailPage';

vi.mock('../api', () => ({
  getStats: vi.fn(),
  getStocks: vi.fn(),
  getEtfs: vi.fn(),
  getStockDetail: vi.fn(),
  getEtfDetail: vi.fn(),
  getStockAnalysis: vi.fn(),
  getEtfAnalysis: vi.fn(),
  getKline: vi.fn(),
  analyze: vi.fn(),
  getJob: vi.fn(),
}));

vi.mock('../components/KlineChart', () => ({
  default: () => <div data-testid="kline-chart" />,
}));

import {
  getStats,
  getStocks,
  getEtfs,
  getStockDetail,
  getStockAnalysis,
  getEtfDetail,
  getEtfAnalysis,
  getKline,
  analyze,
  getJob,
} from '../api';

const stats = { stockCnt: 5348, etfCnt: 624, analyzedCnt: 4832, analyzedTimes: 9000 };

const stockItem = {
  code: 'sz.300750',
  codeName: '宁德时代',
  market: 'SZ',
  industry: '电力设备',
  fullName: null,
  lastTradeDate: '2026-08-13',
  lastClose: 198.4,
  lastPctChg: 2.45,
  lastAmount: 4810000000,
  peTtm: 22.4,
  pb: null,
  totalMarketCap: null,
  high52w: null,
  low52w: null,
  analysis: { date: '2026-08-13', rating: 'A', score: 70, signal: 'BUY' },
};

const etfItem = {
  code: 'sh.510300',
  codeName: '沪深300ETF',
  market: 'SH',
  category: '宽基',
  manager: '华泰柏瑞',
  lastTradeDate: '2026-08-13',
  nav: 4.182,
  lastPctChg: 0.04,
  fundScale: 183200000000,
  analysis: { date: '2026-08-13', rating: 'B+', score: 45, signal: 'HOLD' },
};

beforeEach(() => {
  vi.useRealTimers();
  vi.mocked(getStats).mockResolvedValue(stats);
  vi.mocked(getStocks).mockResolvedValue({
    items: [stockItem],
    total: 4832,
    page: 1,
    pageSize: 20,
  });
  vi.mocked(getEtfs).mockResolvedValue({
    items: [etfItem],
    total: 512,
    page: 1,
    pageSize: 20,
  });
});

describe('HomePage', () => {
  it('渲染统计卡片与覆盖率', async () => {
    render(<HomePage />);
    expect(await screen.findByText('股票 / ETF 数据汇总')).toBeInTheDocument();
    expect(screen.getByText('5,348')).toBeInTheDocument();
    expect(screen.getByText('624')).toBeInTheDocument();
    // 4832/5348 = 90.35% → 90.4%；ETF 卡按 spec 公式用同一 analyzedCnt，封顶 100%
    expect(screen.getByText('90.4%')).toBeInTheDocument();
    expect(screen.getByText('100.0%')).toBeInTheDocument();
  });

  it('接口失败时展示错误与重试', async () => {
    vi.mocked(getStats).mockRejectedValue(new Error('boom'));
    render(<HomePage />);
    expect(await screen.findByText('boom')).toBeInTheDocument();
    expect(screen.getByText('重试')).toBeInTheDocument();
  });
});

describe('StocksPage', () => {
  it('渲染列表、状态标签与分页信息', async () => {
    render(
      <MemoryRouter>
        <StocksPage />
      </MemoryRouter>,
    );
    expect(await screen.findByText('宁德时代')).toBeInTheDocument();
    expect(screen.getAllByText('电力设备').length).toBeGreaterThan(0);
    expect(screen.getByText('+2.45%')).toBeInTheDocument();
    expect(screen.getByText('48.1 亿')).toBeInTheDocument();
    expect(screen.getAllByText('已分析').length).toBeGreaterThan(0);
    expect(screen.getAllByText(/共 4,832 条/).length).toBeGreaterThan(0);
    expect(screen.getByText('下一页')).toBeInTheDocument();
  });

  it('标题展示已分析总数', async () => {
    render(
      <MemoryRouter>
        <StocksPage />
      </MemoryRouter>,
    );
    expect(await screen.findByText(/股票列表 · 4,832 已分析/)).toBeInTheDocument();
  });
});

describe('EtfsPage', () => {
  it('渲染 ETF 列表', async () => {
    render(
      <MemoryRouter>
        <EtfsPage />
      </MemoryRouter>,
    );
    expect(await screen.findByText('沪深300ETF')).toBeInTheDocument();
    expect(screen.getAllByText('华泰柏瑞').length).toBeGreaterThan(0);
    expect(screen.getAllByText('宽基').length).toBeGreaterThan(0);
    expect(screen.getAllByText('4.182').length).toBeGreaterThan(0);
    expect(screen.getByText('1,832 亿')).toBeInTheDocument();
  });
});

describe('DetailPage', () => {
  const detail = {
    code: 'sh.600519',
    codeName: '贵州茅台',
    fullName: '贵州茅台酒股份有限公司',
    market: 'SH',
    type: '1',
    ipoDate: '2001-08-27',
    outDate: null,
    status: '1',
    industry: '白酒',
    lastTradeDate: '2026-08-13',
    lastClose: 1654,
    lastPctChg: -0.42,
    lastAmount: 3240000000,
    peTtm: 24.2,
    pb: 8.6,
    totalMarketCap: 2600000000000,
    high52w: 1789,
    low52w: 1387.5,
  };
  const analysis = {
    date: '2026-08-13',
    score: 82,
    signal: 'BUY',
    rating: 'A+',
    isWorthBuying: 1,
    holdDays: 15,
    trend: '多头',
    momentum20: null,
    volatility20: null,
    volumeRatio: null,
    note: '基本面稳健，估值合理偏低。',
    llmAnalysis: '建议关注支撑位与目标价区间。',
  };

  it('渲染股票详情头部、分析卡片与指标', async () => {
    vi.mocked(getStockDetail).mockResolvedValue(detail);
    vi.mocked(getStockAnalysis).mockResolvedValue({
      items: [analysis],
      total: 1,
      page: 1,
      pageSize: 20,
    });
    vi.mocked(getKline).mockResolvedValue([]);
    render(
      <MemoryRouter initialEntries={['/stocks/sh.600519']}>
        <Routes>
          <Route path="/stocks/:code" element={<DetailPage kind="stock" />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText('贵州茅台')).toBeInTheDocument();
    expect(screen.getByText('600519.SH')).toBeInTheDocument();
    expect(screen.getByText('1,654.00')).toBeInTheDocument();
    expect(screen.getByText('-0.42%')).toBeInTheDocument();
    expect(screen.getByText('A+')).toBeInTheDocument();
    expect(screen.getByText('82 / 100')).toBeInTheDocument();
    expect(screen.getByText('综合评分 · 建议：买入')).toBeInTheDocument();
    expect(screen.getByText('2.60 万亿')).toBeInTheDocument();
    expect(screen.getByText('1,789.00')).toBeInTheDocument();
  });

  it('渲染 ETF 详情（nav 兼容 lastClose）', async () => {
    vi.mocked(getEtfDetail).mockResolvedValue({
      code: 'sh.510300',
      codeName: '沪深300ETF',
      market: 'SH',
      type: '5',
      ipoDate: '2012-05-28',
      outDate: null,
      status: '1',
      category: '宽基',
      manager: '华泰柏瑞',
      lastTradeDate: '2026-08-13',
      lastClose: 4.182,
      lastPctChg: 0.04,
      fundScale: 183200000000,
    });
    vi.mocked(getEtfAnalysis).mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      pageSize: 20,
    });
    vi.mocked(getKline).mockResolvedValue([]);
    render(
      <MemoryRouter initialEntries={['/etfs/sh.510300']}>
        <Routes>
          <Route path="/etfs/:code" element={<DetailPage kind="etf" />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText('沪深300ETF')).toBeInTheDocument();
    expect(screen.getAllByText('4.182').length).toBeGreaterThan(0);
    expect(screen.getByText('暂无分析结果')).toBeInTheDocument();
    expect(screen.getAllByText('华泰柏瑞').length).toBeGreaterThan(0);
  });

  it('点击触发分析后调用 analyze 并轮询 job，完成后刷新分析卡片', async () => {
    vi.mocked(getStockDetail).mockResolvedValue(detail);
    vi.mocked(getStockAnalysis)
      .mockClear()
      .mockResolvedValueOnce({ items: [], total: 0, page: 1, pageSize: 20 })
      .mockResolvedValueOnce({ items: [analysis], total: 1, page: 1, pageSize: 20 });
    vi.mocked(getKline).mockResolvedValue([]);
    vi.mocked(analyze).mockResolvedValue({ accepted: true, jobId: 'job-1' });
    vi.mocked(getJob).mockResolvedValue({ jobId: 'job-1', status: 'done', result: null });

    render(
      <MemoryRouter initialEntries={['/stocks/sh.600519']}>
        <Routes>
          <Route path="/stocks/:code" element={<DetailPage kind="stock" />} />
        </Routes>
      </MemoryRouter>,
    );

    // 初始无分析结果
    expect(await screen.findByText('暂无分析结果')).toBeInTheDocument();

    fireEvent.click(screen.getByText('开始分析'));
    expect(analyze).toHaveBeenCalledWith('stock', 'sh.600519');

    await waitFor(() => expect(getJob).toHaveBeenCalledWith('job-1'));

    // job 完成后重新拉取分析列表，刷新出分析卡片
    await waitFor(() => expect(screen.getByText('A+')).toBeInTheDocument());
    expect(screen.getByText(/综合评分 · 建议/)).toBeInTheDocument();
  });

  it('组件卸载后停止轮询（不产生泄漏请求）', async () => {
    vi.useFakeTimers();
    vi.mocked(getStockDetail).mockResolvedValue(detail);
    vi.mocked(getStockAnalysis)
      .mockClear()
      .mockResolvedValue({ items: [], total: 0, page: 1, pageSize: 20 });
    vi.mocked(getKline).mockResolvedValue([]);
    vi.mocked(analyze).mockResolvedValue({ accepted: true, jobId: 'job-poll' });
    // 一直 running，永不 done，用于观察卸载后是否仍在轮询
    vi.mocked(getJob).mockResolvedValue({ jobId: 'job-poll', status: 'running', result: null });

    const { unmount } = render(
      <MemoryRouter initialEntries={['/stocks/sh.600519']}>
        <Routes>
          <Route path="/stocks/:code" element={<DetailPage kind="stock" />} />
        </Routes>
      </MemoryRouter>,
    );

    // 让初始加载完成
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByText('暂无分析结果')).toBeInTheDocument();

    fireEvent.click(screen.getByText('开始分析'));
    // 触发 analyze 并完成首次轮询
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(getJob).toHaveBeenCalled();
    const callsAfterFirst = vi.mocked(getJob).mock.calls.length;

    unmount();
    // 推进多个轮询周期，若仍存活应继续调用 getJob
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500 * 3);
    });

    // 卸载后不应再产生新的 getJob 调用
    expect(vi.mocked(getJob).mock.calls.length).toBe(callsAfterFirst);
    vi.useRealTimers();
  });

  it('404 时展示错误信息', async () => {
    vi.mocked(getStockDetail).mockRejectedValue(new Error('资源不存在'));
    render(
      <MemoryRouter initialEntries={['/stocks/sh.999999']}>
        <Routes>
          <Route path="/stocks/:code" element={<DetailPage kind="stock" />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText('资源不存在')).toBeInTheDocument();
  });
});
