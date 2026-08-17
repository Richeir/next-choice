"""fetch_data 模块的纯逻辑单元测试（不联网）。"""
from datetime import date, timedelta

import pytest

from fetch_data import _kline_fields, resolve_date_range

YEARS = 5
WINDOW_DAYS = 365 * YEARS


class TestKlineFields:
    def test_valid(self):
        assert _kline_fields("stock", "daily").startswith("date,code")

    def test_etf_daily_has_valuation_cols(self):
        fields = _kline_fields("etf", "daily")
        assert "peTTM" in fields and "pcfNcfTTM" in fields

    @pytest.mark.parametrize("kind,freq", [("bogus", "daily"), ("stock", "bogus")])
    def test_invalid(self, kind, freq):
        with pytest.raises(ValueError):
            _kline_fields(kind, freq)


class TestResolveDateRange:
    def test_both_none_defaults_to_5y_window(self):
        start, end = resolve_date_range(None, None, years=YEARS)
        assert end == date.today().isoformat()
        assert start == (date.today() - timedelta(days=WINDOW_DAYS)).isoformat()

    def test_end_given_start_backfilled(self):
        start, end = resolve_date_range(None, "2024-01-31", years=YEARS)
        assert end == "2024-01-31"
        assert start == "2019-02-01"  # 2024-01-31 往前 5 年

    def test_explicit_start_end_kept(self):
        start, end = resolve_date_range("2024-01-01", "2024-01-31", years=YEARS)
        assert start == "2024-01-01"
        assert end == "2024-01-31"

    def test_custom_years(self):
        start, _ = resolve_date_range(None, "2024-01-31", years=1)
        assert start == "2023-01-31"
