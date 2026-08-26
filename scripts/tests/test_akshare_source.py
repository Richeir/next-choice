"""akshare_source 数据源层单元测试（网络调用全部 mock）。"""
import json

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
                                 sleep=delays.append, jitter=lambda: 0.0)
        assert r == "ok" and len(calls) == 3
        assert delays == [1.0, 4.0]

    def test_backoff_has_jitter(self):
        """齐步重试会把限流放大，退避需带随机抖动。"""
        def fn():
            raise requests.exceptions.ConnectionError("boom")
        delays = []
        with pytest.raises(requests.exceptions.ConnectionError):
            src.fetch_with_retry(fn, max_retries=2, base_delay=1.0,
                                 sleep=delays.append, jitter=lambda: 1.0)
        # 抖动上限 +50%
        assert delays == [1.5, 6.0]

    def test_exhausted_raises(self):
        def fn():
            raise requests.exceptions.ConnectionError("boom")
        with pytest.raises(requests.exceptions.ConnectionError):
            src.fetch_with_retry(fn, max_retries=2, sleep=lambda s: None)

    @pytest.mark.parametrize("exc", [
        KeyError("data"),
        IndexError("list index out of range"),
        json.JSONDecodeError("Expecting value", "", 0),
    ])
    def test_upstream_throttle_shapes_are_retried(self, exc):
        """限流常表现为解析异常而非 HTTP 错误，这些也要重试。"""
        calls = []

        def fn():
            calls.append(1)
            if len(calls) < 3:
                raise exc
            return "ok"
        assert src.fetch_with_retry(fn, max_retries=3, sleep=lambda s: None,
                                    jitter=lambda: 0.0) == "ok"
        assert len(calls) == 3

    def test_programming_error_not_retried(self):
        calls = []

        def fn():
            calls.append(1)
            raise TypeError("bad call")
        with pytest.raises(TypeError):
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
        # 新浪 ETF 接口无 prevclose 列，preclose 回退为上一根 close
        raw = pd.DataFrame([
            ("2023-12-29", 2.99, 3.0, 2.9, 3.0, 500, 1500, 0, 0),
            ("2024-01-02", 3.0, 3.1, 2.95, 3.1, 600, 1860, 0, 0),
        ], columns=["date", "open", "high", "low", "close",
                    "volume", "amount", "postVol", "postAmt"])
        monkeypatch.setattr(src.ak, "fund_etf_hist_sina", lambda symbol: raw)
        df = src.etf_kline("510050", "2024-01-01", "2024-01-31")
        assert len(df) == 1
        assert df.iloc[0]["preclose"] == 3.0


def _kv_df(pairs):
    return pd.DataFrame(pairs, columns=["item", "value"])


class TestListStocks:
    def test_maps_tx_columns_and_units(self, monkeypatch):
        raw = pd.DataFrame([{
            "code": "sh600519", "name": "贵州茅台", "pe_ttm": 19.5,
            "zsz": 15911.41, "zxj": 1272.83, "zdf": -1.45, "turnover": 427831,
        }])
        monkeypatch.setattr(src.ak, "stock_zh_a_spot_tx", lambda: raw)
        rows = src.list_stocks()
        assert rows[0] == {
            "code": "600519", "name": "贵州茅台", "pe_ttm": 19.5,
            "total_market_cap": pytest.approx(15911.41e8),
            "last_close": 1272.83, "last_pct_chg": -1.45,
            "last_amount": pytest.approx(427831e4),
        }


class TestListEtfs:
    def test_maps_sina_columns(self, monkeypatch):
        raw = pd.DataFrame([{"代码": "sh510050", "名称": "华夏上证50ETF"},
                            {"代码": "sz159915", "名称": "创业板ETF"}])
        monkeypatch.setattr(src.ak, "fund_etf_category_sina",
                            lambda symbol: raw)
        assert src.list_etfs() == [
            {"code": "510050", "name": "华夏上证50ETF", "market": "SH"},
            {"code": "159915", "name": "创业板ETF", "market": "SZ"}]


class TestEtfMaps:
    def test_category_map(self, monkeypatch):
        raw = pd.DataFrame([{"基金代码": "510050", "基金类型": "股票型"}])
        monkeypatch.setattr(src.ak, "fund_etf_category_ths",
                            lambda symbol: raw)
        assert src.etf_category_map() == {"510050": "股票型"}

    def test_fund_scale_map(self, monkeypatch):
        raw = pd.DataFrame([{
            "基金代码": "510300", "总募集规模": 3296860.0,
            "基金经理": "柳军", "成立日期": "2012-05-04"}])
        monkeypatch.setattr(src.ak, "fund_scale_open_sina", lambda: raw)
        m = src.fund_scale_map()
        assert m["510300"] == {"fund_scale": pytest.approx(3296860.0e4),
                               "manager": "柳军", "ipo_date": "2012-05-04"}


class TestStockInfoXq:
    @pytest.fixture(autouse=True)
    def _reset_token_state(self, monkeypatch):
        """隔离 XQ_TOKEN 环境与一次性提示标记。"""
        monkeypatch.delenv("XQ_TOKEN", raising=False)
        monkeypatch.setattr(src, "_token_hint_shown", False)

    def test_basic(self, monkeypatch):
        raw = _kv_df([
            ("org_name_cn", "上海浦东发展银行股份有限公司"),
            ("listed_date", 942163200000),  # 1999-11-10 UTC+8
            ("affiliate_industry", {"ind_code": "BK0055", "ind_name": "银行"}),
        ])
        monkeypatch.setattr(src.ak, "stock_individual_basic_info_xq",
                            lambda symbol, token=None: raw)
        info = src.stock_basic("600000")
        assert info == {"full_name": "上海浦东发展银行股份有限公司",
                        "industry": "银行", "ipo_date": "1999-11-10"}

    def test_quote(self, monkeypatch):
        raw = _kv_df([("市净率", 0.5), ("52周最高", 13.6), ("52周最低", 8.1),
                      ("资产净值/总市值", 3.01e11)])
        monkeypatch.setattr(src.ak, "stock_individual_spot_xq",
                            lambda symbol, token=None: raw)
        assert src.stock_quote("600000") == {
            "pb": 0.5, "high_52w": 13.6, "low_52w": 8.1,
            "total_market_cap": 3.01e11}

    def test_quote_non_numeric_value_returns_none(self, monkeypatch):
        """雪球脏数据（如 '-'）不应抛异常，对应字段返回 None。"""
        raw = _kv_df([("市净率", 0.5), ("52周最高", "-"), ("52周最低", "--"),
                      ("资产净值/总市值", 3.01e11)])
        monkeypatch.setattr(src.ak, "stock_individual_spot_xq",
                            lambda symbol, token=None: raw)
        assert src.stock_quote("600000") == {
            "pb": 0.5, "high_52w": None, "low_52w": None,
            "total_market_cap": 3.01e11}

    def test_basic_failure_returns_none(self, monkeypatch):
        def boom(symbol, token=None):
            raise requests.exceptions.ConnectionError("boom")
        monkeypatch.setattr(src.ak, "stock_individual_basic_info_xq", boom)
        assert src.stock_basic("600000", max_retries=0) is None


class TestXqToken:
    @pytest.fixture(autouse=True)
    def _reset_token_state(self, monkeypatch):
        monkeypatch.delenv("XQ_TOKEN", raising=False)
        monkeypatch.setattr(src, "_token_hint_shown", False)

    @pytest.mark.parametrize("raw,expected", [
        ("abc123", "abc123"), ("  abc123  ", "abc123"),
        ("", None), ("   ", None),
    ])
    def test_xq_token_reads_env(self, monkeypatch, raw, expected):
        monkeypatch.setenv("XQ_TOKEN", raw)
        assert src.xq_token() == expected

    def test_xq_token_unset_returns_none(self):
        assert src.xq_token() is None

    def test_token_injected_into_akshare_call(self, monkeypatch):
        """配置 XQ_TOKEN 后必须原样传给 akshare 的 token 参数。"""
        seen = {}

        def fake(symbol, token=None):
            seen["symbol"], seen["token"] = symbol, token
            return _kv_df([("市净率", 0.5)])

        monkeypatch.setenv("XQ_TOKEN", "tok-from-browser")
        monkeypatch.setattr(src.ak, "stock_individual_spot_xq", fake)
        src.stock_quote("600000")
        assert seen == {"symbol": "SH600000", "token": "tok-from-browser"}

    def test_no_env_passes_none_fallback(self, monkeypatch):
        """未配置时 token=None，akshare 回退内置 token（行为不变）。"""
        seen = {}
        monkeypatch.setattr(
            src.ak, "stock_individual_basic_info_xq",
            lambda symbol, token=None: seen.update(symbol=symbol,
                                                   token=token) or _kv_df([]))
        src.stock_basic("600000")
        assert seen == {"symbol": "SH600000", "token": None}

    def test_failure_hint_shown_once_without_token(self, monkeypatch, caplog):
        def boom(symbol, token=None):
            raise RuntimeError("400016 请重新登录")
        monkeypatch.setattr(src.ak, "stock_individual_spot_xq", boom)
        with caplog.at_level("WARNING"):
            assert src.stock_quote("600000") is None
            assert src.stock_quote("600001") is None
        assert caplog.text.count("XQ_TOKEN") == 1

    def test_failure_with_token_hint_mentions_expiry(self, monkeypatch, caplog):
        monkeypatch.setenv("XQ_TOKEN", "stale-token")

        def boom(symbol, token=None):
            raise RuntimeError("400016 请重新登录")
        monkeypatch.setattr(src.ak, "stock_individual_spot_xq", boom)
        with caplog.at_level("WARNING"):
            assert src.stock_quote("600000") is None
        assert "过期" in caplog.text
