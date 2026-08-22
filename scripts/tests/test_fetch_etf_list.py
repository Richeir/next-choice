"""fetch_data.update_etf_list 单元测试：mock akshare_source。"""
import pytest

import db
import fetch_data
from conftest import SCHEMA


@pytest.fixture()
def conn(tmp_path):
    return db.init_db(str(tmp_path / "test.db"), SCHEMA)


class TestUpdateEtfList:
    def test_joins_three_sources(self, conn, monkeypatch):
        monkeypatch.setattr(fetch_data.src, "list_etfs", lambda **kw:
                            [{"code": "510050", "name": "上证50ETF"},
                             {"code": "159915", "name": "创业板ETF"}])
        monkeypatch.setattr(fetch_data.src, "etf_category_map",
                            lambda **kw: {"510050": "股票型"})
        monkeypatch.setattr(fetch_data.src, "fund_scale_map", lambda **kw:
                            {"510050": {"fund_scale": 5.0e10,
                                        "manager": "柳军",
                                        "ipo_date": "2004-12-30"}})
        n_ok, n_fail = fetch_data.update_etf_list(conn)
        assert (n_ok, n_fail) == (2, 0)
        row = conn.execute(
            "SELECT * FROM etf_info WHERE code='510050'").fetchone()
        assert row["market"] == "SH" and row["type"] == "5"
        assert row["category"] == "股票型"
        assert row["manager"] == "柳军"
        assert row["fund_scale"] == 5.0e10
        assert row["ipoDate"] == "2004-12-30"
        row2 = conn.execute(
            "SELECT category, manager, fund_scale FROM etf_info"
            " WHERE code='159915'").fetchone()
        assert row2["category"] is None and row2["manager"] is None
        assert row2["fund_scale"] is None
