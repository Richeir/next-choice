"""fetch_data 股票 K 线命令单元测试：mock akshare_source。"""
import pandas as pd
import pytest

import db
import fetch_data
from conftest import SCHEMA

COLS = fetch_data.src.KLINE_COLS


def _df(rows):
    return pd.DataFrame(rows, columns=COLS)


@pytest.fixture()
def conn(tmp_path):
    c = db.init_db(str(tmp_path / "test.db"), SCHEMA)
    c.execute("INSERT INTO stock_info (code, code_name, market, type, status)"
              " VALUES ('600000','浦发银行','SH','1','1')")
    c.commit()
    return c


def _two_days():
    return _df([("2024-01-02", 10, 11, 9, 10.5, 9.9, 1000, 1e4, 1.0, 6.06),
                ("2024-01-03", 10.5, 12, 10, 11.0, 10.5, 2000, 2e4, 2.0, 4.76)])


class TestFetchStockKline:
    def test_daily_two_adjusts(self, conn, monkeypatch):
        seen = []

        def fake(code, start, end, adjust="", max_retries=3):
            seen.append(adjust)
            return _two_days()
        monkeypatch.setattr(fetch_data.src, "stock_kline", fake)
        n_ok, n_fail = fetch_data.fetch_stock_kline(
            conn, ["daily"], ["2", "3"], "2024-01-01", "2024-01-31",
            sleep_s=0)
        assert (n_ok, n_fail) == (1, 0)
        assert sorted(seen) == ["", "qfq"]
        rows = conn.execute("SELECT adjustflag, count(*) n FROM"
                            " stock_kline_daily GROUP BY adjustflag").fetchall()
        assert {r["adjustflag"]: r["n"] for r in rows} == {"2": 2, "3": 2}

    def test_daily_row_fields(self, conn, monkeypatch):
        monkeypatch.setattr(fetch_data.src, "stock_kline",
                            lambda *a, **kw: _two_days())
        fetch_data.fetch_stock_kline(conn, ["daily"], ["3"],
                                     "2024-01-01", "2024-01-31", sleep_s=0)
        row = conn.execute("SELECT * FROM stock_kline_daily"
                           " WHERE date='2024-01-03'").fetchone()
        assert row["preclose"] == 10.5
        assert row["tradestatus"] == "1" and row["isST"] == "0"
        assert row["turn"] == 2.0

    def test_weekly_resampled(self, conn, monkeypatch):
        monkeypatch.setattr(fetch_data.src, "stock_kline",
                            lambda *a, **kw: _two_days())
        fetch_data.fetch_stock_kline(conn, ["weekly"], ["3"],
                                     "2024-01-01", "2024-01-31", sleep_s=0)
        row = conn.execute("SELECT * FROM stock_kline_weekly").fetchone()
        assert row["date"] == "2024-01-03"
        assert row["open"] == 10 and row["close"] == 11.0
        assert row["volume"] == 3000

    def test_source_failure_counts_fail(self, conn, monkeypatch):
        monkeypatch.setattr(fetch_data.src, "stock_kline",
                            lambda *a, **kw: None)
        n_ok, n_fail = fetch_data.fetch_stock_kline(
            conn, ["daily"], ["3"], "2024-01-01", "2024-01-31", sleep_s=0)
        assert (n_ok, n_fail) == (0, 1)
