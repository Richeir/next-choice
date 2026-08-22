"""fetch_data.fetch_etf_info 单元测试：雪球逐只补齐 ETF 52周高低。"""
import pytest

import db
import fetch_data
from conftest import SCHEMA


@pytest.fixture()
def conn(tmp_path):
    c = db.init_db(str(tmp_path / "test.db"), SCHEMA)
    c.execute("INSERT INTO etf_info (code, code_name, market, type, status)"
              " VALUES ('510050','上证50ETF','SH','5','1')")
    c.execute("INSERT INTO etf_info (code, code_name, market, type, status,"
              " high_52w, low_52w) VALUES"
              " ('510300','沪深300ETF','SH','5','1', 4.0, 3.0)")
    c.commit()
    return c


class TestFetchEtfInfo:
    def test_only_fills_missing(self, conn, monkeypatch):
        calls = []

        def fake_quote(code, **kw):
            calls.append(code)
            return {"pb": None, "high_52w": 3.256, "low_52w": 2.851,
                    "total_market_cap": 2.18e10}
        monkeypatch.setattr(fetch_data.src, "stock_quote", fake_quote)
        n_ok, n_fail = fetch_data.fetch_etf_info(conn, sleep_s=0)
        assert (n_ok, n_fail) == (1, 0)
        assert calls == ["510050"]  # 510300 已有 high_52w，跳过
        row = conn.execute("SELECT * FROM etf_info WHERE code='510050'"
                           ).fetchone()
        assert row["high_52w"] == 3.256 and row["low_52w"] == 2.851
        # 未抓过的行不受影响
        row2 = conn.execute("SELECT * FROM etf_info WHERE code='510300'"
                            ).fetchone()
        assert row2["high_52w"] == 4.0 and row2["low_52w"] == 3.0

    def test_limit_zero(self, conn, monkeypatch):
        monkeypatch.setattr(fetch_data.src, "stock_quote",
                            lambda code, **kw: None)
        n_ok, n_fail = fetch_data.fetch_etf_info(conn, limit=0, sleep_s=0)
        assert (n_ok, n_fail) == (0, 0)

    def test_source_failure_counts_fail(self, conn, monkeypatch):
        monkeypatch.setattr(fetch_data.src, "stock_quote",
                            lambda code, **kw: None)
        n_ok, n_fail = fetch_data.fetch_etf_info(conn, sleep_s=0)
        assert (n_ok, n_fail) == (0, 1)

    def test_quote_without_52w_fields_counts_ok(self, conn, monkeypatch):
        """quote 成功但无 52 周字段（如数据源缺失）：记 ok 不写库。"""
        monkeypatch.setattr(fetch_data.src, "stock_quote",
                            lambda code, **kw: {"pb": None, "high_52w": None,
                                                "low_52w": None})
        n_ok, n_fail = fetch_data.fetch_etf_info(conn, sleep_s=0)
        assert (n_ok, n_fail) == (1, 0)
        row = conn.execute("SELECT * FROM etf_info WHERE code='510050'"
                           ).fetchone()
        assert row["high_52w"] is None and row["low_52w"] is None

    def test_unexpected_error_counts_fail_and_continues(self, conn,
                                                        monkeypatch):
        """单只意外异常（如脏数据）记 fail 继续，不中断整体。"""
        conn.execute("INSERT INTO etf_info (code, code_name, market, type,"
                     " status) VALUES ('159915','创业板ETF','SZ','5','1')")
        conn.commit()

        def quote(code, **kw):
            if code == "159915":
                raise ValueError("bad data")
            return {"high_52w": 3.256, "low_52w": 2.851}
        monkeypatch.setattr(fetch_data.src, "stock_quote", quote)
        n_ok, n_fail = fetch_data.fetch_etf_info(conn, sleep_s=0)
        assert (n_ok, n_fail) == (1, 1)
