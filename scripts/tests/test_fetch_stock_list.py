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

    def test_upsert_preserves_xq_backfilled_fields(self, conn, monkeypatch):
        """列表刷新不得擦除雪球逐只补齐的字段（full_name/industry/PB/52周等）。"""
        conn.execute("INSERT INTO stock_info (code, code_name, market, type,"
                     " status, full_name, industry, ipoDate, pb, high_52w,"
                     " low_52w) VALUES ('600000','旧名','SH','1','1',"
                     " '上海浦东发展银行股份有限公司','银行','1999-11-10',"
                     " 0.5, 13.6, 8.1)")
        conn.commit()
        monkeypatch.setattr(fetch_data.src, "list_stocks",
                            lambda **kw: _stocks())
        fetch_data.update_stock_list(conn)
        row = conn.execute(
            "SELECT * FROM stock_info WHERE code='600000'").fetchone()
        # 列表字段被刷新
        assert row["code_name"] == "浦发银行" and row["last_close"] == 9.05
        # 雪球补齐字段保留（注意 total_market_cap 由列表源刷新，不保留）
        assert row["full_name"] == "上海浦东发展银行股份有限公司"
        assert row["industry"] == "银行" and row["ipoDate"] == "1999-11-10"
        assert row["pb"] == 0.5
        assert row["high_52w"] == 13.6 and row["low_52w"] == 8.1

    def test_unknown_segment_skipped(self, conn, monkeypatch):
        rows = _stocks() + [{"code": "920045", "name": "北交所样本",
                             "pe_ttm": None, "total_market_cap": None,
                             "last_close": 1.0, "last_pct_chg": 0.0,
                             "last_amount": 1.0}]
        monkeypatch.setattr(fetch_data.src, "list_stocks",
                            lambda **kw: rows)
        n_ok, n_skip = fetch_data.update_stock_list(conn)
        assert (n_ok, n_skip) == (2, 1)
        assert conn.execute(
            "SELECT count(*) c FROM stock_info WHERE code='920045'"
        ).fetchone()["c"] == 0
