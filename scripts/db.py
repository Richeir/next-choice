"""SQLite 数据库封装：建库、幂等写入 K 线、行情回填。

schema 单一定义来源为 backend/database/schema.sql（与 Nest.js 后端共用），
本模块负责读取并执行建表。
"""
import os
import sqlite3

from transform import kline_table, to_float

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_PATH = os.path.join(ROOT, "backend", "database", "schema.sql")

# 每种 K 线表的列集合（与 schema.sql / db-design.md 一致）。
# row 的列顺序必须与此对应。
_TABLE_COLS = {
    ("stock", "daily"): [
        "date", "code", "open", "high", "low", "close", "preclose",
        "volume", "amount", "adjustflag", "turn", "tradestatus", "pctChg", "isST",
    ],
    ("stock", "weekly"): [
        "date", "code", "open", "high", "low", "close",
        "volume", "amount", "adjustflag", "turn", "pctChg",
    ],
    ("stock", "monthly"): [
        "date", "code", "open", "high", "low", "close",
        "volume", "amount", "adjustflag", "turn", "pctChg",
    ],
    ("etf", "daily"): [
        "date", "code", "open", "high", "low", "close", "preclose",
        "volume", "amount", "adjustflag", "turn", "tradestatus", "pctChg", "isST",
        "peTTM", "pbMRQ", "psTTM", "pcfNcfTTM",
    ],
    ("etf", "weekly"): [
        "date", "code", "open", "high", "low", "close",
        "volume", "amount", "adjustflag", "turn", "pctChg",
    ],
    ("etf", "monthly"): [
        "date", "code", "open", "high", "low", "close",
        "volume", "amount", "adjustflag", "turn", "pctChg",
    ],
}

# 保持字符串原样的列（不转 float）
_RAW_COLS = {"date", "code", "adjustflag", "tradestatus", "isST"}


def init_db(db_path, schema_path=None):
    """连接 db_path 并按 schema.sql 建表（幂等），返回 sqlite3 连接。"""
    schema_path = schema_path or SCHEMA_PATH
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    with open(schema_path, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    return conn


def _kline_columns(kind, freq):
    try:
        return _TABLE_COLS[(kind, freq)]
    except KeyError:
        raise ValueError(f"unknown kline table: kind={kind!r} freq={freq!r}")


def insert_kline(conn, kind, freq, adjustflag, rows):
    """批量写入 K 线（INSERT OR REPLACE，幂等）。

    rows: list[list]，每行列顺序与 _TABLE_COLS[(kind, freq)] 对应。
    数值列自动转 float，date/code/adjustflag/tradestatus/isST 保持原样。
    """
    columns = _kline_columns(kind, freq)
    table = kline_table(kind, freq)
    sql = (
        f"INSERT OR REPLACE INTO {table} ({','.join(columns)}) "
        f"VALUES ({','.join('?' for _ in columns)})"
    )
    adj_idx = columns.index("adjustflag")
    for row in rows:
        if row[adj_idx] != adjustflag:
            raise ValueError(
                f"row adjustflag {row[adj_idx]!r} != param {adjustflag!r}"
            )
        vals = [v if c in _RAW_COLS else to_float(v) for c, v in zip(columns, row)]
        conn.execute(sql, vals)
    conn.commit()


def backfill_stock_info(conn):
    """用不复权日 K 回填 stock_info 的脚本可回填字段（取每 code 日期最大一行）。"""
    conn.execute(
        """
        UPDATE stock_info
        SET last_trade_date = k.date,
            last_close      = k.close,
            last_pct_chg    = k.pctChg
        FROM (
            SELECT code, date, close, pctChg,
                   ROW_NUMBER() OVER (PARTITION BY code ORDER BY date DESC) AS rn
            FROM stock_kline_daily
            WHERE adjustflag = '3'
        ) AS k
        WHERE stock_info.code = k.code AND k.rn = 1
        """
    )
    conn.commit()


def backfill_etf_info(conn):
    """用不复权日 K 回填 etf_info 的脚本可回填字段（取每 code 日期最大一行）。"""
    conn.execute(
        """
        UPDATE etf_info
        SET last_trade_date = k.date,
            last_close      = k.close,
            last_pct_chg    = k.pctChg
        FROM (
            SELECT code, date, close, pctChg,
                   ROW_NUMBER() OVER (PARTITION BY code ORDER BY date DESC) AS rn
            FROM etf_kline_daily
            WHERE adjustflag = '3'
        ) AS k
        WHERE etf_info.code = k.code AND k.rn = 1
        """
    )
    conn.commit()
