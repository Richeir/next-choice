"""db 模块单元测试：建表、幂等写入。全部用临时 SQLite 文件，不打网络。"""
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
    "analysis_config",
    "analysis_jobs",
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
            ["2024-01-02", "600000", "6.63", "6.65", "6.60", "6.60",
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
            ["2024-01-02", "600000", "6.99", "6.99", "6.99", "6.99",
             "6.99", "1", "1", "3", "0", "1", "0", "0"],
        ],
    )
    n = conn.execute(
        "SELECT COUNT(*) FROM stock_kline_daily WHERE code='600000' AND date='2024-01-02'"
    ).fetchone()[0]
    assert n == 1


def test_insert_kline_wrong_table(conn):
    with pytest.raises(ValueError):
        db.insert_kline(conn, kind="bogus", freq="daily", adjustflag="3", rows=[])


def test_insert_kline_stores_requested_adjustflag(conn):
    # 落库应记录请求的复权方式，而非信任数据源返回的 adjustflag 列。
    db.insert_kline(
        conn,
        kind="stock",
        freq="daily",
        adjustflag="2",
        rows=[
            ["2024-01-02", "600000", "6.63", "6.65", "6.60", "6.60",
             "6.60", "22066700", "146066303", "3", "0.0752", "1", "-0.3021", "0"],
        ],
    )
    row = conn.execute(
        "SELECT adjustflag FROM stock_kline_daily "
        "WHERE code='600000' AND date='2024-01-02'"
    ).fetchone()
    assert row["adjustflag"] == "2"


def test_insert_kline_protects_preclose_pctchg_from_null(conn):
    """重叠重拉时新行 preclose/pctChg 为 NULL 不得覆盖已有值；
    其他列正常覆盖。"""
    db.insert_kline(
        conn, kind="stock", freq="daily", adjustflag="3",
        rows=[["2024-01-02", "600000", 10.0, 11.0, 9.0, 10.0, 9.5,
               1000, 10000, "3", 1.0, "1", 5.26, "0"]],
    )
    # 增量窗口首行：preclose / pctChg 缺失（None），close 等正常
    db.insert_kline(
        conn, kind="stock", freq="daily", adjustflag="3",
        rows=[["2024-01-02", "600000", 10.0, 11.0, 9.0, 10.5, None,
               1000, 10000, "3", 1.0, "1", None, "0"]],
    )
    row = conn.execute(
        "SELECT close, preclose, pctChg FROM stock_kline_daily "
        "WHERE code='600000' AND date='2024-01-02'"
    ).fetchone()
    assert row["close"] == 10.5       # 普通列被覆盖
    assert row["preclose"] == 9.5     # NULL 不覆盖已有值
    assert row["pctChg"] == 5.26


def test_insert_kline_null_overwrites_null(conn):
    """库中原值也是 NULL 时，NULL 写入保持 NULL（不报错）。"""
    db.insert_kline(
        conn, kind="stock", freq="daily", adjustflag="3",
        rows=[["2024-01-02", "600000", 10.0, 11.0, 9.0, 10.0, None,
               1000, 10000, "3", 1.0, "1", None, "0"]],
    )
    db.insert_kline(
        conn, kind="stock", freq="daily", adjustflag="3",
        rows=[["2024-01-02", "600000", 10.0, 11.0, 9.0, 10.0, None,
               1000, 10000, "3", 1.0, "1", None, "0"]],
    )
    row = conn.execute(
        "SELECT preclose, pctChg FROM stock_kline_daily "
        "WHERE code='600000' AND date='2024-01-02'"
    ).fetchone()
    assert row["preclose"] is None and row["pctChg"] is None


def test_insert_kline_wrong_row_length(conn):
    # 行字段数少于列集应显式报错，避免 zip 静默截断
    with pytest.raises(ValueError):
        db.insert_kline(
            conn,
            kind="stock",
            freq="daily",
            adjustflag="3",
            rows=[["2024-01-02", "600000", "6.63"]],
        )


def test_schema_has_last_fetch_date(conn):
    for t in ["stock_info", "etf_info"]:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({t})")]
        assert "last_fetch_date" in cols


def test_migrate_adds_last_fetch_date_to_old_table(tmp_path):
    # 旧库（无 last_fetch_date 列）经 _migrate 应补齐该列
    conn = sqlite3.connect(str(tmp_path / "old.db"))
    conn.execute(
        "CREATE TABLE stock_info (code TEXT PRIMARY KEY, code_name TEXT)"
    )
    conn.execute(
        "CREATE TABLE etf_info (code TEXT PRIMARY KEY, code_name TEXT)"
    )
    conn.commit()
    db._migrate(conn)
    for t in ["stock_info", "etf_info"]:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({t})")]
        assert "last_fetch_date" in cols
    # etf_info 还应补齐雪球 52 周高低列
    cols = [r[1] for r in conn.execute("PRAGMA table_info(etf_info)")]
    assert "high_52w" in cols and "low_52w" in cols
    conn.close()


def test_mark_fetched_and_fetched_today(conn):
    conn.execute(
        "INSERT INTO stock_info (code, code_name, type, market) VALUES "
        "('600000','浦发银行','1','SH')"
    )
    conn.execute(
        "INSERT INTO stock_info (code, code_name, type, market) VALUES "
        "('000001','平安银行','1','SZ')"
    )
    conn.commit()
    assert db.fetched_today(conn, "stock", "2026-08-18") == set()
    db.mark_fetched(conn, "stock", "600000", "2026-08-18")
    assert db.fetched_today(conn, "stock", "2026-08-18") == {"600000"}
    assert db.fetched_today(conn, "stock", "2026-08-19") == set()
