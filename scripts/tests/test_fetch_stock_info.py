"""fetch_data.fetch_stock_info 单元测试：雪球逐只补齐，跳过已抓过的。"""
import pytest

import db
import fetch_data
from conftest import SCHEMA


@pytest.fixture()
def conn(tmp_path):
    c = db.init_db(str(tmp_path / "test.db"), SCHEMA)
    c.execute("INSERT INTO stock_info (code, code_name, market, type, status)"
              " VALUES ('600000','浦发银行','SH','1','1')")
    c.execute("INSERT INTO stock_info (code, code_name, market, type, status,"
              " full_name) VALUES ('000001','平安银行','SZ','1','1','已抓过')")
    c.commit()
    return c


class TestFetchStockInfo:
    def test_only_fills_missing(self, conn, monkeypatch):
        calls = []

        def fake_basic(code, **kw):
            calls.append(code)
            return {"full_name": "上海浦东发展银行股份有限公司",
                    "industry": "银行", "ipo_date": "1999-11-10"}
        monkeypatch.setattr(fetch_data.src, "stock_basic", fake_basic)
        monkeypatch.setattr(fetch_data.src, "stock_quote",
                            lambda code, **kw: {"pb": 0.5, "high_52w": 13.6,
                                                "low_52w": 8.1,
                                                "total_market_cap": 3.01e11})
        n_ok, n_fail = fetch_data.fetch_stock_info(conn, sleep_s=0)
        assert (n_ok, n_fail) == (1, 0)
        assert calls == ["600000"]  # 000001 已有 full_name，跳过
        row = conn.execute("SELECT * FROM stock_info WHERE code='600000'"
                           ).fetchone()
        assert row["full_name"] == "上海浦东发展银行股份有限公司"
        assert row["industry"] == "银行"
        assert row["ipoDate"] == "1999-11-10"
        assert row["pb"] == 0.5 and row["high_52w"] == 13.6
        assert row["low_52w"] == 8.1
        assert row["total_market_cap"] == 3.01e11

    def test_limit_zero(self, conn, monkeypatch):
        monkeypatch.setattr(fetch_data.src, "stock_basic",
                            lambda code, **kw: None)
        monkeypatch.setattr(fetch_data.src, "stock_quote",
                            lambda code, **kw: None)
        n_ok, n_fail = fetch_data.fetch_stock_info(conn, limit=0, sleep_s=0)
        assert (n_ok, n_fail) == (0, 0)

    def test_source_failure_counts_fail(self, conn, monkeypatch):
        monkeypatch.setattr(fetch_data.src, "stock_basic",
                            lambda code, **kw: None)
        monkeypatch.setattr(fetch_data.src, "stock_quote",
                            lambda code, **kw: None)
        n_ok, n_fail = fetch_data.fetch_stock_info(conn, sleep_s=0)
        assert (n_ok, n_fail) == (0, 1)
