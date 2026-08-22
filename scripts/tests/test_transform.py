"""transform 工具函数单元测试。"""
import pytest

from transform import is_etf_code, kline_table, market_of, to_float


class TestMarketOf:
    @pytest.mark.parametrize("code,market", [
        ("600000", "SH"), ("601398", "SH"), ("688981", "SH"),
        ("000001", "SZ"), ("300750", "SZ"), ("002594", "SZ"),
        ("510050", "SH"), ("560010", "SH"), ("588000", "SH"),
        ("159915", "SZ"), ("161725", "SZ"),
    ])
    def test_market_by_code_segment(self, code, market):
        assert market_of(code) == market

    def test_unknown_segment_raises(self):
        with pytest.raises(ValueError):
            market_of("900000")
        with pytest.raises(ValueError):
            market_of("sh.600000")


class TestIsEtfCode:
    @pytest.mark.parametrize("code", ["510050", "560010", "588000",
                                      "159915", "161725"])
    def test_etf_segments(self, code):
        assert is_etf_code(code) is True

    @pytest.mark.parametrize("code", ["600000", "688981", "000001",
                                      "300750", "900000"])
    def test_non_etf_segments(self, code):
        assert is_etf_code(code) is False


class TestToFloat:
    def test_empty_and_none(self):
        assert to_float("") is None
        assert to_float(None) is None

    def test_nan(self):
        assert to_float(float("nan")) is None

    def test_number(self):
        assert to_float("3.5") == 3.5
        assert to_float(2) == 2.0


class TestKlineTable:
    def test_ok(self):
        assert kline_table("stock", "daily") == "stock_kline_daily"

    def test_invalid(self):
        with pytest.raises(ValueError):
            kline_table("bond", "daily")
