"""db 模块单元测试：建表、幂等写入、行情回填。全部用临时 SQLite 文件，不打网络。"""
import sqlite3

import pytest

import db
from conftest import SCHEMA

EXPECTED_TABLES = {
    "stock_info",
    "etf_info",
    "stock_kline_daily",
    "stock_kline_weekly",
    "stock_kline_monthly",
    "etf_kline_daily",
    "etf_kline_weekly",
    "etf_kline_monthly",
    "stock_analysis",
    "etf_analysis",
    "adjust_factor",
}


@pytest.fixture()
def conn(tmp_path):
    return db.init_db(str(tmp_path / "test.db"), SCHEMA)


def test_init_db_creates_all_tables(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    got = {r[0] for r in rows}
    assert EXPECTED_TABLES == got


def test_kline_primary_key_unique(conn):
    db.insert_kline(
        conn,
        kind="stock",
        freq="daily",
        adjustflag="3",
        rows=[
            ["2024-01-02", "sh.600000", "6.63", "6.65", "6.60", "6.60",
             "6.60", "22066700", "146066303", "3", "0.0752", "1", "-0.3021", "0"],
        ],
    )
    # 幂等：重复写同主键，行数不变
    db.insert_kline(
        conn,
        kind="stock",
        freq="daily",
        adjustflag="3",
        rows=[
            ["2024-01-02", "sh.600000", "6.99", "6.99", "6.99", "6.99",
             "6.99", "1", "1", "3", "0", "1", "0", "0"],
        ],
    )
    n = conn.execute(
        "SELECT COUNT(*) FROM stock_kline_daily WHERE code='sh.600000' AND date='2024-01-02'"
    ).fetchone()[0]
    assert n == 1


def test_insert_kline_wrong_table(conn):
    with pytest.raises(ValueError):
        db.insert_kline(conn, kind="bogus", freq="daily", adjustflag="3", rows=[])


def test_stock_backfill(conn):
    # 先插基础信息 + 两行不复权日 K（含 peTTM）
    conn.execute(
        "INSERT INTO stock_info (code, code_name, type, market) VALUES ('sh.600000','浦发银行','1','SH')"
    )
    db.insert_kline(
        conn,
        kind="stock",
        freq="daily",
        adjustflag="3",
        rows=[
            ["2024-01-02", "sh.600000", "6.63", "6.65", "6.60", "6.60",
             "6.60", "22066700", "146066303", "3", "0.0752", "1", "-0.3021", "0"],
            ["2024-01-05", "sh.600000", "6.60", "6.76", "6.59", "6.68",
             "6.60", "44421387", "296976885", "3", "0.1513", "1", "0.9063", "0"],
        ],
    )
    db.backfill_stock_info(conn)
    row = conn.execute(
        "SELECT last_trade_date, last_close, last_pct_chg FROM stock_info WHERE code='sh.600000'"
    ).fetchone()
    # 回填应取 date 最大的一行
    assert tuple(row) == ("2024-01-05", 6.68, 0.9063)


def test_etf_backfill(conn):
    conn.execute(
        "INSERT INTO etf_info (code, code_name, type, market) VALUES ('sh.510010','上证50ETF','5','SH')"
    )
    db.insert_kline(
        conn,
        kind="etf",
        freq="daily",
        adjustflag="3",
        rows=[
            ["2024-01-02", "sh.510010", "1.80", "1.83", "1.80", "1.82",
             "1.80", "161200", "294216", "3", "0.1147", "1", "1.2735", "1",
             "", "", "", ""],
            ["2024-01-03", "sh.510010", "1.82", "1.84", "1.81", "1.83",
             "1.81", "200000", "400000", "3", "0.2", "1", "0.5", "1",
             "", "", "", ""],
        ],
    )
    db.backfill_etf_info(conn)
    row = conn.execute(
        "SELECT last_trade_date, last_close, last_pct_chg FROM etf_info WHERE code='sh.510010'"
    ).fetchone()
    assert tuple(row) == ("2024-01-03", 1.83, 0.5)
