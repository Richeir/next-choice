"""SQLite 数据库封装：建库、幂等写入 K 线。

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
    _migrate(conn)
    return conn


# 对旧库做增量迁移：schema.sql 用 CREATE TABLE IF NOT EXISTS，不会给已存在的
# 表补列，故对缺失的列单独 ALTER TABLE ADD COLUMN。
_INFO_MIGRATIONS = [
    ("stock_info", "last_fetch_date", "TEXT"),
    ("etf_info", "last_fetch_date", "TEXT"),
    ("etf_info", "high_52w", "REAL"),
    ("etf_info", "low_52w", "REAL"),
]


def _migrate(conn):
    """为已存在的 info 表补充新增列（幂等）。"""
    for table, col, coltype in _INFO_MIGRATIONS:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        if col not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")
    conn.commit()


def mark_fetched(conn, kind, code, date_str):
    """把某证券（stock/etf）的 last_fetch_date 标记为指定日期（断点续传）。"""
    conn.execute(
        f"UPDATE {kind}_info SET last_fetch_date=? WHERE code=?",
        (date_str, code),
    )
    conn.commit()


def fetched_today(conn, kind, date_str):
    """返回 last_fetch_date 等于指定日期的证券 code 集合（用于跳过已完成的）。"""
    rows = conn.execute(
        f"SELECT code FROM {kind}_info WHERE last_fetch_date=?", (date_str,)
    )
    return {r["code"] for r in rows}


def kline_max_date(conn, kind, freq):
    """返回 K 线表中每只证券的最后一根 K 线日期 {code: 'YYYY-MM-DD'}。

    跨 adjustflag 聚合（各档复权数据日期一致）；空表返回 {}。
    增量更新用它确定每只证券的抓取起始日（从最后日期重拉一天覆盖修正）。
    """
    table = kline_table(kind, freq)
    rows = conn.execute(
        f"SELECT code, MAX(date) AS d FROM {table} GROUP BY code"
    )
    return {r["code"]: r["d"] for r in rows}


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
        if len(row) != len(columns):
            raise ValueError(
                f"{table}: row has {len(row)} fields, expected {len(columns)}"
            )
        # 落库记录请求的复权方式，不信任数据源返回的 adjustflag 列。
        row[adj_idx] = adjustflag
        vals = [v if c in _RAW_COLS else to_float(v) for c, v in zip(columns, row)]
        conn.execute(sql, vals)
    conn.commit()
