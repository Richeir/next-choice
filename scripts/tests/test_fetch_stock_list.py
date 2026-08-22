"""fetch_data.update_stock_list 单元测试：mock akshare_source。"""
import pytest

import db
import fetch_data
from conftest import SCHEMA


@pytest.fixture()
def conn(tmp_path):
    return db.init_db(str(tmp_path / "test.db"), SCHEMA)


def _stocks():
    return [{"code": "600000", "name": "浦发银行", "pe_ttm": 4.2,
             "total_market_cap": 3.01e11, "last_close": 9.05,
             "last_pct_chg": -0.66, "last_amount": 4.28e9},
            {"code": "000001", "name": "平安银行", "pe_ttm": 5.1,
             "total_market_cap": 2.0e11, "last_close": 10.3,
             "last_pct_chg": 0.5, "last_amount": 1.0e9}]


class TestUpdateStockList:
    def test_writes_all_fields(self, conn, monkeypatch):
        monkeypatch.setattr(fetch_data.src, "list_stocks",
                            lambda **kw: _stocks())
        n_ok, n_fail = fetch_data.update_stock_list(conn)
        assert (n_ok, n_fail) == (2, 0)
        row = conn.execute(
            "SELECT * FROM stock_info WHERE code='600000'").fetchone()
        assert row["code_name"] == "浦发银行"
        assert row["market"] == "SH"
        assert row["type"] == "1" and row["status"] == "1"
        assert row["pe_ttm"] == 4.2
        assert row["total_market_cap"] == 3.01e11
        assert row["last_amount"] == 4.28e9
        assert row["last_close"] == 9.05
        assert row["last_pct_chg"] == -0.66
        assert row["last_trade_date"] is not None

    def test_market_sz(self, conn, monkeypatch):
        monkeypatch.setattr(fetch_data.src, "list_stocks",
                            lambda **kw: _stocks())
        fetch_data.update_stock_list(conn)
        row = conn.execute(
            "SELECT market FROM stock_info WHERE code='000001'").fetchone()
        assert row["market"] == "SZ"
