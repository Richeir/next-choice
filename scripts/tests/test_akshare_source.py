"""akshare_source 数据源层单元测试（网络调用全部 mock）。"""
import pytest
import requests

import akshare_source as src


class TestCodeConversion:
    def test_to_sina(self):
        assert src.to_sina_code("600000") == "sh600000"
        assert src.to_sina_code("000001") == "sz000001"

    def test_to_xq(self):
        assert src.to_xq_code("600000") == "SH600000"
        assert src.to_xq_code("159915") == "SZ159915"

    def test_strip_prefix(self):
        assert src.strip_prefix("sh600000") == "600000"
        assert src.strip_prefix("sz000001") == "000001"


class TestUnits:
    def test_yi_to_yuan(self):
        assert src.yi_to_yuan(1.5) == 1.5e8
        assert src.yi_to_yuan(None) is None

    def test_wan_to_yuan(self):
        assert src.wan_to_yuan(2.5) == 2.5e4
        assert src.wan_to_yuan(None) is None


class TestRetry:
    def test_success_no_retry(self):
        calls = []

        def fn():
            calls.append(1)
            return "ok"
        assert src.fetch_with_retry(fn, max_retries=3, sleep=lambda s: None) == "ok"
        assert len(calls) == 1

    def test_retry_then_success(self):
        calls = []

        def fn():
            calls.append(1)
            if len(calls) < 3:
                raise requests.exceptions.ConnectionError("boom")
            return "ok"
        delays = []
        r = src.fetch_with_retry(fn, max_retries=3, base_delay=1.0,
                                 sleep=delays.append)
        assert r == "ok" and len(calls) == 3
        assert delays == [1.0, 4.0]

    def test_exhausted_raises(self):
        def fn():
            raise requests.exceptions.ConnectionError("boom")
        with pytest.raises(requests.exceptions.ConnectionError):
            src.fetch_with_retry(fn, max_retries=2, sleep=lambda s: None)

    def test_non_network_error_not_retried(self):
        calls = []

        def fn():
            calls.append(1)
            raise KeyError("data")
        with pytest.raises(KeyError):
            src.fetch_with_retry(fn, max_retries=3, sleep=lambda s: None)
        assert len(calls) == 1


import pandas as pd


def _daily_df():
    # 2024-01-02(二) ~ 2024-01-05(五)，同一交易周
    rows = [
        ("2024-01-02", 10.0, 11.0, 9.0, 10.5, 9.9, 1000, 10500, 1.0),
        ("2024-01-03", 10.5, 12.0, 10.0, 11.0, 10.5, 2000, 22000, 2.0),
        ("2024-01-04", 11.0, 11.5, 10.5, 10.8, 11.0, 1500, 16200, 1.5),
        ("2024-01-05", 10.8, 11.2, 10.2, 11.1, 10.8, 1800, 19980, 1.8),
    ]
    cols = ["date", "open", "high", "low", "close", "preclose",
            "volume", "amount", "turn"]
    return pd.DataFrame(rows, columns=cols)


class TestResample:
    def test_weekly_groups_by_week(self):
        out = src.resample_kline(_daily_df(), "weekly")
        assert len(out) == 1
        r = out.iloc[0]
        assert r["date"] == "2024-01-05"      # 组内最后交易日
        assert r["open"] == 10.0 and r["close"] == 11.1
        assert r["high"] == 12.0 and r["low"] == 9.0
        assert r["volume"] == 6300 and r["amount"] == 68680
        assert pd.isna(r["turn"])

    def test_monthly(self):
        out = src.resample_kline(_daily_df(), "monthly")
        assert len(out) == 1 and out.iloc[0]["close"] == 11.1

    def test_two_weeks_preclose_and_pct(self):
        d1 = _daily_df()
        d2 = _daily_df()
        d2["date"] = ["2024-01-08", "2024-01-09", "2024-01-10", "2024-01-11"]
        out = src.resample_kline(pd.concat([d1, d2], ignore_index=True), "weekly")
        assert len(out) == 2
        assert out.iloc[1]["preclose"] == 11.1
        assert out.iloc[1]["pctChg"] == pytest.approx(0.0)
        assert pd.isna(out.iloc[0]["preclose"])

    def test_invalid_freq(self):
        with pytest.raises(ValueError):
            src.resample_kline(_daily_df(), "daily")


class TestKlineNormalize:
    def test_stock_kline_normalizes(self, monkeypatch):
        raw = pd.DataFrame([
            ("2024-01-02", 10.0, 11.0, 9.0, 10.5, 1000, 10500, 1e10, 1.0),
            ("2024-01-03", 10.5, 12.0, 10.0, 11.0, 2000, 22000, 1e10, 2.0),
        ], columns=["date", "open", "high", "low", "close",
                    "volume", "amount", "outstanding_share", "turnover"])
        monkeypatch.setattr(src.ak, "stock_zh_a_daily", lambda **kw: raw)
        df = src.stock_kline("600000", "2024-01-01", "2024-01-31", adjust="qfq")
        assert list(df.columns) == src.KLINE_COLS
        assert pd.isna(df.iloc[0]["preclose"])
        assert df.iloc[1]["preclose"] == 10.5
        assert df.iloc[1]["pctChg"] == pytest.approx((11.0 / 10.5 - 1) * 100)
        assert df.iloc[1]["turn"] == 2.0

    def test_stock_kline_failure_returns_none(self, monkeypatch):
        def boom(**kw):
            raise requests.exceptions.ConnectionError("boom")
        monkeypatch.setattr(src.ak, "stock_zh_a_daily", boom)
        assert src.stock_kline("600000", "2024-01-01", "2024-01-31",
                               max_retries=0) is None

    def test_etf_kline_filters_dates(self, monkeypatch):
        raw = pd.DataFrame([
            ("2023-12-29", 2.99, 3.0, 3.1, 2.9, 3.0, 500, 1500, 0, 0),
            ("2024-01-02", 3.0, 3.0, 3.2, 2.95, 3.1, 600, 1860, 0, 0),
        ], columns=["date", "prevclose", "open", "high", "low", "close",
                    "volume", "amount", "postVol", "postAmt"])
        monkeypatch.setattr(src.ak, "fund_etf_hist_sina", lambda symbol: raw)
        df = src.etf_kline("510050", "2024-01-01", "2024-01-31")
        assert len(df) == 1
        assert df.iloc[0]["preclose"] == 3.0
