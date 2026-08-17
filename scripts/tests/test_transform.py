"""transform 模块单元测试：BaoStock str 值转换、市场推断、表名映射。"""
import pytest

from transform import kline_table, market_of, to_float


class TestToFloat:
    def test_plain_number(self):
        assert to_float("6.6300") == 6.63

    def test_empty_string_is_none(self):
        assert to_float("") is None

    def test_none_is_none(self):
        assert to_float(None) is None

    def test_float_passthrough(self):
        assert to_float(6.63) == 6.63

    def test_int_passthrough(self):
        assert to_float(0) == 0.0


class TestMarketOf:
    def test_shanghai(self):
        assert market_of("sh.600000") == "SH"

    def test_shenzhen(self):
        assert market_of("sz.000001") == "SZ"

    def test_etf_shanghai(self):
        assert market_of("sh.510010") == "SH"

    def test_etf_shenzhen(self):
        assert market_of("sz.159915") == "SZ"


class TestKlineTable:
    @pytest.mark.parametrize(
        "kind,freq,expected",
        [
            ("stock", "daily", "stock_kline_daily"),
            ("stock", "weekly", "stock_kline_weekly"),
            ("stock", "monthly", "stock_kline_monthly"),
            ("etf", "daily", "etf_kline_daily"),
            ("etf", "weekly", "etf_kline_weekly"),
            ("etf", "monthly", "etf_kline_monthly"),
        ],
    )
    def test_mapping(self, kind, freq, expected):
        assert kline_table(kind, freq) == expected
