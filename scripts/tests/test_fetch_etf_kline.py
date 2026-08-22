"""fetch_data ETF K 线命令单元测试：mock akshare_source。"""
import pandas as pd
import pytest

import db
import fetch_data
from conftest import SCHEMA


def _df(rows):
    return pd.DataFrame(rows, columns=fetch_data.src.KLINE_COLS)


@pytest.fixture()
def conn(tmp_path):
    c = db.init_db(str(tmp_path / "test.db"), SCHEMA)
    c.execute("INSERT INTO etf_info (code, code_name, market, type, status)"
              " VALUES ('510050','上证50ETF','SH','5','1')")
    c.commit()
    return c


class TestFetchEtfKline:
    def test_adjust_forced_to_3(self, conn, monkeypatch):
        monkeypatch.setattr(fetch_data.src, "etf_kline", lambda *a, **kw: _df(
            [("2024-01-02", 3.0, 3.1, 2.9, 3.05, 2.99, 500, 1500, None, 2.0)]))
        n_ok, n_fail = fetch_data.fetch_etf_kline(
            conn, ["daily"], ["2", "3"], "2024-01-01", "2024-01-31", sleep_s=0)
        assert (n_ok, n_fail) == (1, 0)
        rows = conn.execute("SELECT adjustflag FROM etf_kline_daily").fetchall()
        assert [r["adjustflag"] for r in rows] == ["3"]

    def test_valuation_columns_null(self, conn, monkeypatch):
        monkeypatch.setattr(fetch_data.src, "etf_kline", lambda *a, **kw: _df(
            [("2024-01-02", 3.0, 3.1, 2.9, 3.05, 2.99, 500, 1500, None, 2.0)]))
        fetch_data.fetch_etf_kline(conn, ["daily"], ["3"],
                                   "2024-01-01", "2024-01-31", sleep_s=0)
        row = conn.execute("SELECT * FROM etf_kline_daily").fetchone()
        assert row["peTTM"] is None and row["pbMRQ"] is None
        assert row["psTTM"] is None and row["pcfNcfTTM"] is None
        assert row["preclose"] == 2.99
