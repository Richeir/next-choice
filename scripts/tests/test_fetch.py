"""fetch_data run_fetch（--codes 路径）与 CLI 解析测试。"""
import pandas as pd
import pytest

import db
import fetch_data
from conftest import SCHEMA


@pytest.fixture()
def conn(tmp_path):
    return db.init_db(str(tmp_path / "test.db"), SCHEMA)


class TestRunFetch:
    def test_stock_codes(self, conn, monkeypatch):
        monkeypatch.setattr(fetch_data.src, "stock_basic",
                            lambda code, **kw: {"full_name": "全称",
                                                "industry": "银行",
                                                "ipo_date": "1999-11-10"})
        monkeypatch.setattr(fetch_data.src, "stock_kline",
                            lambda *a, **kw: pd.DataFrame(
                                [("2024-01-02", 10, 11, 9, 10.5, 9.9,
                                  1000, 1e4, 1.0, 6.0)],
                                columns=fetch_data.src.KLINE_COLS))
        fetch_data.run_fetch(conn, ["600000"], ["daily"], ["3"],
                             "2024-01-01", "2024-01-31")
        info = conn.execute("SELECT * FROM stock_info WHERE code='600000'"
                            ).fetchone()
        assert info["code_name"] == "全称"  # 无列表源时用 full_name
        assert info["industry"] == "银行"
        assert conn.execute("SELECT count(*) c FROM stock_kline_daily"
                            ).fetchone()["c"] == 1

    def test_etf_codes(self, conn, monkeypatch):
        monkeypatch.setattr(fetch_data.src, "etf_kline",
                            lambda *a, **kw: pd.DataFrame(
                                [("2024-01-02", 3.0, 3.1, 2.9, 3.05, 2.99,
                                  500, 1500, None, 2.0)],
                                columns=fetch_data.src.KLINE_COLS))
        fetch_data.run_fetch(conn, ["510050"], ["daily"], ["3"],
                             "2024-01-01", "2024-01-31")
        assert conn.execute("SELECT count(*) c FROM etf_kline_daily"
                            ).fetchone()["c"] == 1


class TestParser:
    def test_mutually_exclusive(self):
        with pytest.raises(SystemExit):
            fetch_data.build_parser().parse_args(
                ["--update-stock-list", "--update-etf-list"])

    def test_requires_command(self):
        with pytest.raises(SystemExit):
            fetch_data.build_parser().parse_args([])
