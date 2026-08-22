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


class TestUpdate52wOnKline:
    """K 线抓取成功后用不复权日 K 重算 52 周高低并回写 stock_info。"""

    def test_covered_updates_52w(self, conn, monkeypatch):
        # 存量不复权日 K：窗口内一根；窗口外一根（仅用于覆盖判定，
        # 其 99/0.5 不应进入 52 周计算）
        conn.execute("INSERT INTO stock_kline_daily"
                     " (date, code, high, low, adjustflag)"
                     " VALUES ('2023-02-01','600000',20,5,'3')")
        conn.execute("INSERT INTO stock_kline_daily"
                     " (date, code, high, low, adjustflag)"
                     " VALUES ('2023-01-15','600000',99,0.5,'3')")
        conn.commit()
        monkeypatch.setattr(fetch_data.src, "stock_kline", lambda *a, **kw:
                            _df([("2024-01-30", 14, 15, 8, 9, 14.5, 100,
                                  1e3, 1.0, 7.0)]))
        fetch_data.fetch_stock_kline(conn, ["daily"], ["3"],
                                     "2023-01-01", "2024-01-31",
                                     today="2024-01-31", sleep_s=0)
        row = conn.execute("SELECT high_52w, low_52w FROM stock_info"
                           " WHERE code='600000'").fetchone()
        assert row["high_52w"] == 20
        assert row["low_52w"] == 5

    def test_52w_update_failure_keeps_kline_ok(self, conn, monkeypatch):
        """52w 回写异常不应计为 K 线抓取失败。"""
        monkeypatch.setattr(fetch_data.src, "stock_kline",
                            lambda *a, **kw: _two_days())

        def boom(*a, **kw):
            raise RuntimeError("boom")
        monkeypatch.setattr(fetch_data, "_update_52w_from_kline", boom)
        n_ok, n_fail = fetch_data.fetch_stock_kline(
            conn, ["daily"], ["3"], "2024-01-01", "2024-01-31",
            today="2024-01-31", sleep_s=0)
        assert (n_ok, n_fail) == (1, 0)

    def test_not_covered_keeps_old_52w(self, conn, monkeypatch):
        # 日 K 覆盖不足 52 周窗口：保留雪球原值不覆盖
        conn.execute("UPDATE stock_info SET high_52w=999, low_52w=111")
        conn.commit()
        monkeypatch.setattr(fetch_data.src, "stock_kline",
                            lambda *a, **kw: _two_days())
        fetch_data.fetch_stock_kline(conn, ["daily"], ["3"],
                                     "2024-01-01", "2024-01-31",
                                     today="2024-01-31", sleep_s=0)
        row = conn.execute("SELECT high_52w, low_52w FROM stock_info"
                           " WHERE code='600000'").fetchone()
        assert row["high_52w"] == 999
        assert row["low_52w"] == 111
