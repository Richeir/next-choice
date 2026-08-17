#!/usr/bin/env python3
"""BaoStock 数据采集脚本（股票 / ETF 基础信息 + 日/周/月 K 线）。

用法示例：
    python fetch_data.py --db data/market.db \
        --codes sh.600000,sz.159915 \
        --freq daily,weekly,monthly --adjust 2,3 \
        --start 2024-01-01 --end 2024-01-31

流程：login -> 逐个 code 写基础信息 -> 逐个 (code, freq, adjust) 拉 K 线入库
      -> 用不复权日 K 回填行情字段 -> logout。
"""
import argparse
import os
import sys
from datetime import date, timedelta

import baostock as bs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import (SCHEMA_PATH, backfill_etf_info, backfill_stock_info,
                init_db, insert_kline)
from transform import kline_table, market_of

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FREQ_PARAM = {"daily": "d", "weekly": "w", "monthly": "m"}
VALID_ADJUST = ("2", "3")


def _kline_fields(kind, freq):
    kline_table(kind, freq)  # 校验 kind/freq，非法值抛 ValueError
    from db import _TABLE_COLS
    return ",".join(_TABLE_COLS[(kind, freq)])


def resolve_date_range(start, end, years=5):
    """解析抓取日期窗口。

    文档未定义采集默认回溯窗口；此处约定为：未指定时默认回溯 N 年
    （默认 5 年）。end 缺省取今天，start 缺省取 end 往前 N 年。
    """
    if end is None:
        end = date.today().isoformat()
    if start is None:
        start = (date.fromisoformat(end) - timedelta(days=365 * years)).isoformat()
    return start, end


def fetch_basic(conn, code):
    """拉取并写入单个 code 的基础信息（stock_info 或 etf_info），返回证券 type。"""
    rs = bs.query_stock_basic(code=code)
    if rs.error_code != "0":
        raise RuntimeError(
            f"query_stock_basic {code} failed: {rs.error_code} {rs.error_msg}"
        )
    if not rs.next():
        raise RuntimeError(f"no basic info for {code}")
    row = rs.get_row_data()  # [code, code_name, ipoDate, outDate, type, status]
    _, code_name, ipo, out, stype, status = row
    market = market_of(code)
    cols = (
        "code, code_name, market, type, ipoDate, outDate, status"
    )
    if stype == "1":  # 股票
        table = "stock_info"
    elif stype == "5":  # ETF
        table = "etf_info"
    else:
        raise RuntimeError(f"unsupported type {stype!r} for {code}")
    sql = (
        f"INSERT OR REPLACE INTO {table} ({cols}) VALUES (?,?,?,?,?,?,?)"
    )
    conn.execute(
        sql, (code, code_name, market, stype, ipo or None, out or None, status)
    )
    conn.commit()
    return stype


def fetch_kline(conn, kind, code, freq, adjustflag, start, end):
    """拉取单个 (code, freq, adjustflag) 的 K 线并幂等入库。"""
    if adjustflag not in VALID_ADJUST:
        raise ValueError(f"invalid adjustflag: {adjustflag!r}")
    fields = _kline_fields(kind, freq)
    rs = bs.query_history_k_data_plus(
        code,
        fields,
        start_date=start,
        end_date=end,
        frequency=FREQ_PARAM[freq],
        adjustflag=adjustflag,
    )
    if rs.error_code != "0":
        raise RuntimeError(
            f"query_history_k_data_plus {code} {freq} {adjustflag} failed: "
            f"{rs.error_code} {rs.error_msg}"
        )
    rows = []
    while rs.next():
        rows.append(rs.get_row_data())
    insert_kline(conn, kind, freq, adjustflag, rows)
    return len(rows)


def run_fetch(conn, codes, freqs, adjusts, start, end):
    """采集主流程：基础信息 + K 线 + 回填。"""
    for code in codes:
        stype = fetch_basic(conn, code)
        kind = "stock" if stype == "1" else "etf"
        for freq in freqs:
            for adj in adjusts:
                fetch_kline(conn, kind, code, freq, adj, start, end)
    backfill_stock_info(conn)
    backfill_etf_info(conn)


def main(argv=None):
    parser = argparse.ArgumentParser(description="BaoStock 数据采集")
    parser.add_argument("--db", default=os.path.join(ROOT, "data", "market.db"))
    parser.add_argument("--codes", required=True,
                        help="逗号分隔的证券代码，如 sh.600000,sz.159915")
    parser.add_argument("--freq", default="daily",
                        help="逗号分隔频率: daily,weekly,monthly")
    parser.add_argument("--adjust", default="3",
                        help="逗号分隔复权: 2(前复权)/3(不复权)")
    parser.add_argument("--start", default=None, help="起始日期 YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="结束日期 YYYY-MM-DD")
    args = parser.parse_args(argv)

    freqs = [f.strip() for f in args.freq.split(",") if f.strip()]
    adjusts = [a.strip() for a in args.adjust.split(",") if a.strip()]
    codes = [c.strip() for c in args.codes.split(",") if c.strip()]

    start, end = resolve_date_range(args.start, args.end)

    conn = init_db(args.db)
    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"baostock login failed: {lg.error_code} {lg.error_msg}")
    try:
        run_fetch(conn, codes, freqs, adjusts, start, end)
    finally:
        bs.logout()
    conn.close()
    print(f"done. db={args.db} codes={codes} freqs={freqs} adjusts={adjusts}")


if __name__ == "__main__":
    main()
