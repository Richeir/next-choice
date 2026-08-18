#!/usr/bin/env python3
"""BaoStock 数据采集脚本（股票 / ETF 基础信息 + 日/周/月 K 线）。

用法示例：
    # 指定代码抓基础信息 + K 线（股票/ETF）
    python fetch_data.py --db data/market.db \
        --codes sh.600000,sz.159915 \
        --freq daily,weekly,monthly --adjust 2,3 \
        --start 2024-01-01 --end 2024-01-31

    # 仅拉取当日全部 ETF 列表并写入 etf_info（不带 K 线；
    # --list-date 指定日期，默认今天；每 100 只批量落库并打印进度）
    python fetch_data.py --update-etf-list [--list-date 2026-08-17]

    # 仅拉取当日全部 A 股列表并写入 stock_info（不带 K 线；
    # --list-date 指定日期，默认今天；每 100 只批量落库并打印进度）
    python fetch_data.py --update-stock-list [--list-date 2026-08-17]

    # 根据 etf_info 表全量抓取 ETF 的日/周/月 K 线（先跑 --update-etf-list
    # 填充 etf_info；默认复权 2,3，--start 控制起始日）
    python fetch_data.py --fetch-etf-kline --freq daily,weekly,monthly \
        --start 2026-01-05

流程：login -> 逐个 code 写基础信息 -> 逐个 (code, freq, adjust) 拉 K 线入库
      -> 用不复权日 K 回填行情字段 -> logout。
"""
import argparse
import logging
import os
import sys
from datetime import date, timedelta

import baostock as bs

log = logging.getLogger(__name__)

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


def update_stock_list(conn, date_str):
    """拉取当日全部 A 股列表，逐只补齐基础信息写入 stock_info。

    数据源：
      1. `query_daily_history_k_AStock(date)` 给出当日所有可交易 A 股的 code
         （5110+ 行，一次拿全；不含 ETF、不含指数）；
      2. 对每个 code 调 `query_stock_basic(code)` 拿 name/ipoDate/outDate/type/status。
    单只 basic 失败或拿到非 type='1'（防御性，AStock 理论上不会返回 ETF）
    只记 warning，不中断整体（~5100 只 A 股，单只失败不应阻塞）。
    返回 (n_ok, n_fail) 供调用方打印汇总。
    """
    rs = bs.query_daily_history_k_AStock(date=date_str)
    if rs.error_code != "0":
        raise RuntimeError(
            f"query_daily_history_k_AStock failed: {rs.error_code} {rs.error_msg}"
        )
    codes = []
    seen = set()
    while rs.next():
        # fields[1] = 'code'（固定，见 baostock 协议）
        code = rs.get_row_data()[1]
        if code not in seen:
            seen.add(code)
            codes.append(code)
    log.info("query_daily_history_k_AStock %s -> %d AStock codes", date_str, len(codes))
    print(f"[stock-list] {date_str}: {len(codes)} codes fetched", flush=True)

    cols = "code, code_name, market, type, ipoDate, outDate, status"
    sql = f"INSERT OR REPLACE INTO stock_info ({cols}) VALUES (?,?,?,?,?,?,?)"

    n_ok = n_fail = 0
    total = len(codes)
    for idx, code in enumerate(codes, 1):
        brs = bs.query_stock_basic(code=code)
        if brs.error_code != "0" or not brs.next():
            log.warning(
                "query_stock_basic %s failed: %s %s",
                code, brs.error_code, brs.error_msg,
            )
            n_fail += 1
            continue
        _, code_name, ipo, out, stype, status = brs.get_row_data()
        if stype != "1":  # 防御：非股票不入 stock_info
            log.warning("skip %s: stock_basic type=%r, not stock", code, stype)
            n_fail += 1
            continue
        market = market_of(code)
        conn.execute(
            sql, (code, code_name, market, stype, ipo or None, out or None, status)
        )
        n_ok += 1
        if idx % 100 == 0 or idx == total:
            log.info("stock progress %d/%d ok=%d fail=%d", idx, total, n_ok, n_fail)
            conn.commit()  # 分批提交：中断不丢已处理数据，便于外部实时查看
            print(
                f"[stock-progress] {idx}/{total} ok={n_ok} fail={n_fail}",
                flush=True,
            )
    return n_ok, n_fail


def update_etf_list(conn, date_str):
    """拉取当日全部 ETF 列表，逐只补齐基础信息写入 etf_info。

    数据源：
      1. `query_daily_history_k_ETF(date)` 给出当日所有 ETF 的 code；
      2. 对每个 code 调 `query_stock_basic(code)` 拿基础信息。
    单只 basic 失败只记 warning 不中断整体（~1419 只 ETF，单只失败不应阻塞）。
    返回 (n_ok, n_fail) 供调用方打印汇总。
    """
    rs = bs.query_daily_history_k_ETF(date=date_str)
    if rs.error_code != "0":
        raise RuntimeError(
            f"query_daily_history_k_ETF failed: {rs.error_code} {rs.error_msg}"
        )
    codes = []
    seen = set()
    while rs.next():
        code = rs.get_row_data()[1]
        if code not in seen:
            seen.add(code)
            codes.append(code)
    log.info("query_daily_history_k_ETF %s -> %d ETF codes", date_str, len(codes))
    print(f"[etf-list] {date_str}: {len(codes)} codes fetched", flush=True)

    cols = "code, code_name, market, type, ipoDate, outDate, status"
    sql = f"INSERT OR REPLACE INTO etf_info ({cols}) VALUES (?,?,?,?,?,?,?)"

    n_ok = n_fail = 0
    total = len(codes)
    for idx, code in enumerate(codes, 1):
        brs = bs.query_stock_basic(code=code)
        if brs.error_code != "0" or not brs.next():
            log.warning(
                "query_stock_basic %s failed: %s %s",
                code, brs.error_code, brs.error_msg,
            )
            n_fail += 1
            continue
        _, code_name, ipo, out, stype, status = brs.get_row_data()
        if stype != "5":  # 防御：非 ETF 不入 etf_info
            log.warning("skip %s: stock_basic type=%r, not ETF", code, stype)
            n_fail += 1
            continue
        market = market_of(code)
        conn.execute(
            sql, (code, code_name, market, stype, ipo or None, out or None, status)
        )
        n_ok += 1
        if idx % 100 == 0 or idx == total:
            log.info("etf progress %d/%d ok=%d fail=%d", idx, total, n_ok, n_fail)
            conn.commit()  # 分批提交：中断不丢已处理数据，也便于外部实时查看
            print(
                f"[etf-progress] {idx}/{total} ok={n_ok} fail={n_fail}",
                flush=True,
            )
    return n_ok, n_fail


def fetch_etf_kline(conn, freqs, adjusts, start, end):
    """从 etf_info 表读全部 code，逐个抓 K 线（日/周/月 × 复权）。

    依赖 etf_info 表已由 `--update-etf-list` 填充；本命令不重新查询列表接口。
    单只失败只记 warning 不中断整体（~1400 只 ETF，单只失败不应阻塞）。
    结束后用不复权日 K 回填 etf_info 行情字段。
    返回 (n_ok, n_fail) 供调用方打印汇总。
    """
    codes = [r["code"] for r in conn.execute("SELECT code FROM etf_info")]
    n_ok = n_fail = 0
    total = len(codes)
    for idx, code in enumerate(codes, 1):
        try:
            for freq in freqs:
                for adj in adjusts:
                    fetch_kline(conn, "etf", code, freq, adj, start, end)
            n_ok += 1
        except (RuntimeError, ValueError) as e:
            log.warning("fetch_kline %s failed: %s", code, e)
            n_fail += 1
        if idx % 100 == 0 or idx == total:
            log.info("etf kline progress %d/%d ok=%d fail=%d", idx, total, n_ok, n_fail)
            conn.commit()  # 分批提交：中断不丢已处理数据
            print(f"[etf-kline-progress] {idx}/{total} ok={n_ok} fail={n_fail}", flush=True)
    backfill_etf_info(conn)
    return n_ok, n_fail


def build_parser():
    """构造 CLI 参数解析器。--codes 与 --update-etf-list 二选一。"""
    parser = argparse.ArgumentParser(description="BaoStock 数据采集")
    parser.add_argument("--db", default=os.path.join(ROOT, "data", "market.db"))
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--codes",
                       help="逗号分隔的证券代码，如 sh.600000,sz.159915")
    group.add_argument("--update-etf-list", action="store_true",
                       help="拉取当日全部 ETF 基础信息并写入 etf_info 表")
    group.add_argument("--update-stock-list", action="store_true",
                       help="拉取当日全部 A 股基础信息并写入 stock_info 表")
    group.add_argument("--fetch-etf-kline", action="store_true",
                       help="根据 etf_info 表全量抓取 ETF 的日/周/月 K 线")
    parser.add_argument("--freq", default="daily",
                        help="逗号分隔频率: daily,weekly,monthly")
    parser.add_argument("--adjust", default=None,
                        help="逗号分隔复权: 2(前复权)/3(不复权)；"
                             "--codes 缺省 3，--fetch-etf-kline 缺省 2,3")
    parser.add_argument("--start", default=None, help="起始日期 YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="结束日期 YYYY-MM-DD")
    parser.add_argument("--list-date", default=None,
                        help="--update-etf-list 使用的日期 YYYY-MM-DD，默认今天")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    conn = init_db(args.db)
    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"baostock login failed: {lg.error_code} {lg.error_msg}")
    try:
        if args.update_etf_list:
            list_date = args.list_date or date.today().isoformat()
            n_ok, n_fail = update_etf_list(conn, list_date)
            print(f"done. db={args.db} etf_list ok={n_ok} fail={n_fail} date={list_date}")
        elif args.update_stock_list:
            list_date = args.list_date or date.today().isoformat()
            n_ok, n_fail = update_stock_list(conn, list_date)
            print(f"done. db={args.db} stock_list ok={n_ok} fail={n_fail} date={list_date}")
        elif args.fetch_etf_kline:
            freqs = [f.strip() for f in args.freq.split(",") if f.strip()]
            # db-design.md：每张 K 线表同时保存 前复权(2) 与 不复权(3)；
            # --fetch-etf-kline 默认 2,3，可用 --adjust 覆盖。
            adjusts = ([a.strip() for a in args.adjust.split(",") if a.strip()]
                       if args.adjust else ["2", "3"])
            start, end = resolve_date_range(args.start, args.end)
            n_ok, n_fail = fetch_etf_kline(conn, freqs, adjusts, start, end)
            print(f"done. db={args.db} etf_kline ok={n_ok} fail={n_fail} "
                  f"freqs={freqs} adjusts={adjusts} start={start} end={end}")
        else:
            freqs = [f.strip() for f in args.freq.split(",") if f.strip()]
            # 指定代码路径保持原缺省：不复权(3)
            adjusts = ([a.strip() for a in args.adjust.split(",") if a.strip()]
                       if args.adjust else ["3"])
            codes = [c.strip() for c in args.codes.split(",") if c.strip()]
            start, end = resolve_date_range(args.start, args.end)
            run_fetch(conn, codes, freqs, adjusts, start, end)
            print(f"done. db={args.db} codes={codes} freqs={freqs} adjusts={adjusts}")
    finally:
        bs.logout()
    conn.close()


if __name__ == "__main__":
    main()
