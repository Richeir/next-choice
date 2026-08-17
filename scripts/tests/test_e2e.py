"""E2E 测试：真实连接 BaoStock 拉取少量数据写入真实 SQLite，验证端到端。

量级很小（1 只股票、日 K、单一复权、一周区间），由用户批准发起真实网络请求。
"""
import pytest

import baostock as bs
from conftest import SCHEMA
from db import init_db
from fetch_data import fetch_basic, fetch_kline, run_fetch

pytestmark = pytest.mark.e2e


def test_e2e_stock_pipeline(tmp_path):
    conn = init_db(str(tmp_path / "market.db"), SCHEMA)
    lg = bs.login()
    assert lg.error_code == "0", f"login failed: {lg.error_msg}"
    try:
        run_fetch(
            conn,
            codes=["sh.600000"],
            freqs=["daily"],
            adjusts=["3"],
            start="2024-01-02",
            end="2024-01-05",
        )
    finally:
        bs.logout()

    # 基础信息入库
    info = conn.execute(
        "SELECT code_name, market, type FROM stock_info WHERE code='sh.600000'"
    ).fetchone()
    assert info is not None
    assert info["code_name"] and info["market"] == "SH"

    # K 线入库（4 个交易日）
    n = conn.execute(
        "SELECT COUNT(*) FROM stock_kline_daily "
        "WHERE code='sh.600000' AND adjustflag='3'"
    ).fetchone()[0]
    assert n >= 1

    # 行情回填成功
    back = conn.execute(
        "SELECT last_trade_date, last_close, last_pct_chg "
        "FROM stock_info WHERE code='sh.600000'"
    ).fetchone()
    assert back is not None
    assert back["last_close"] is not None
    assert back["last_trade_date"] == "2024-01-05"


def test_e2e_etf_pipeline(tmp_path):
    # ETF K 线数据范围自 2026-01-05 起，故用 2026 区间验证
    conn = init_db(str(tmp_path / "etf.db"), SCHEMA)
    lg = bs.login()
    assert lg.error_code == "0"
    try:
        run_fetch(
            conn,
            codes=["sz.159915"],
            freqs=["daily"],
            adjusts=["3"],
            start="2026-02-01",
            end="2026-02-05",
        )
    finally:
        bs.logout()

    info = conn.execute(
        "SELECT code_name, market, type FROM etf_info WHERE code='sz.159915'"
    ).fetchone()
    assert info is not None
    assert info["code_name"] and info["market"] == "SZ"

    n = conn.execute(
        "SELECT COUNT(*) FROM etf_kline_daily "
        "WHERE code='sz.159915' AND adjustflag='3'"
    ).fetchone()[0]
    assert n >= 1

    back = conn.execute(
        "SELECT last_trade_date, last_close FROM etf_info WHERE code='sz.159915'"
    ).fetchone()
    assert back["last_trade_date"] == "2026-02-05"
    assert back["last_close"] is not None


def test_e2e_fetch_kline_count(tmp_path):
    conn = init_db(str(tmp_path / "market.db"), SCHEMA)
    lg = bs.login()
    assert lg.error_code == "0"
    try:
        n = fetch_kline(
            conn, "stock", "sh.600000", "daily", "3",
            "2024-01-02", "2024-01-05",
        )
    finally:
        bs.logout()
    assert n == 4
