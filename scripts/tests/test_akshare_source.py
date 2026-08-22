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
