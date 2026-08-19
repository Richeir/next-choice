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

    # 根据 stock_info 表全量抓取 A 股的日/周/月 K 线（先跑 --update-stock-list
    # 填充 stock_info；默认复权 2,3，--start 控制起始日）
    python fetch_data.py --fetch-stock-kline --freq daily,weekly,monthly \
        --start 2026-01-05

    # 日常增量更新（需已有全量数据）：从每只证券最后一根 K 线日期开始抓，
    # 按频率门控：daily 仅工作日；weekly 周六/周日或距今超 7 天；
    # monthly 月初前 3 天或距今超 31 天（股票/ETF 同理）
    python fetch_data.py --fetch-stock-kline --freq daily,weekly,monthly \
        --incremental

流程：login -> 逐个 code 写基础信息 -> 逐个 (code, freq, adjust) 拉 K 线入库
      -> 用不复权日 K 回填行情字段 -> logout。
"""
import argparse
import logging
import os
import socket
import sys
from datetime import date, timedelta

import baostock as bs

log = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import (SCHEMA_PATH, backfill_etf_info, backfill_stock_info,
                fetched_today, init_db, insert_kline, kline_max_date,
                mark_fetched)
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


def _due_freqs(freqs, today, last_dates):
    """增量模式频率门控：返回该证券本次需要更新的频率列表。

    today: datetime.date；last_dates: {freq: 最后一根 K 线日期 'YYYY-MM-DD' 或 None}。
    None 表示该频率无数据（新证券）——不门控，直接拉取补全。
    规则（仅对已有数据的频率生效）：
    - daily:   仅周一～周五更新（周末不开盘）；
    - weekly:  周六/周日（周 K 周六生成），或最后一根周 K 距今 >7 天（补漏）；
    - monthly: 月初前 3 天（day<=3），或最后一根月 K 距今 >31 天（补漏）。
    """
    due = []
    for f in freqs:
        last = last_dates.get(f)
        if last is None:
            due.append(f)
        elif f == "daily":
            if today.weekday() < 5:
                due.append(f)
        elif f == "weekly":
            if today.weekday() >= 5 or (today - date.fromisoformat(last)).days > 7:
                due.append(f)
        elif f == "monthly":
            if today.day <= 3 or (today - date.fromisoformat(last)).days > 31:
                due.append(f)
    return due


def _kline_fetch_loop(conn, kind, table, freqs, adjusts, start, end, force, today,
                      incremental=False):
    """K 线抓取通用主循环（股票/ETF 共用，支持全量与增量两种模式）。

    从 {kind}_info 表读全部 code，逐个抓日/周/月 × 复权 K 线。
    - 断点续传：`force=False` 时跳过 last_fetch_date==today 的证券；
    - 全量模式：本次请求覆盖全部三档（daily+weekly+monthly）且该证券所有组合
      都成功时，才把 last_fetch_date 记为 today（满足“日/周/月都更新完才标记”）；
    - 增量模式（incremental=True）：每只证券按 DB 中最后 K 线日期决定起始日与
      频率门控（见 _due_freqs），本轮“应更”频率全部成功即标记。
    单只失败记 warning 不中断整体；每只抓完即提交。
    返回 (n_ok, n_fail) 供调用方打印汇总。
    """
    today = today or date.today().isoformat()
    today_dt = date.fromisoformat(today)
    fullset = set(freqs) == {"daily", "weekly", "monthly"}
    codes = [r["code"] for r in conn.execute(f"SELECT code FROM {table}")]
    done = set() if force else fetched_today(conn, kind, today)
    # 增量模式：每张 K 线表一次性预加载各证券最后日期，避免逐只查库
    max_dates = ({f: kline_max_date(conn, kind, f) for f in freqs}
                 if incremental else {})
    n_ok = n_fail = n_skip = 0
    total = len(codes)
    for idx, code in enumerate(codes, 1):
        if code in done:
            n_skip += 1
            log.info("%s kline %d/%d code=%s skipped (fetched today)", kind, idx, total, code)
            print(f"[{kind}-kline] {idx}/{total} {code} skip ok={n_ok} fail={n_fail} skip={n_skip}", flush=True)
            continue
        if incremental:
            last_dates = {f: max_dates[f].get(code) for f in freqs}
            due = _due_freqs(freqs, today_dt, last_dates)
            if not due:
                n_skip += 1
                log.info("%s kline %d/%d code=%s skipped (nothing due)", kind, idx, total, code)
                print(f"[{kind}-kline] {idx}/{total} {code} skip(not due) ok={n_ok} fail={n_fail} skip={n_skip}", flush=True)
                continue
            loop_freqs = due
        else:
            last_dates = {}
            loop_freqs = freqs
        success = True
        try:
            for freq in loop_freqs:
                # 增量：从 DB 最后日期重拉（覆盖修正）；无数据回退到 start
                fstart = (last_dates.get(freq) or start) if incremental else start
                for adj in adjusts:
                    fetch_kline(conn, kind, code, freq, adj, fstart, end)
            n_ok += 1
        except (RuntimeError, ValueError, socket.timeout) as e:
            log.warning("fetch_kline %s failed: %s", code, e)
            n_fail += 1
            success = False
        # 标记：全量需三档全集成功；增量只需本轮“应更”频率全部成功
        if success and (incremental or fullset):
            mark_fetched(conn, kind, code, today)
        conn.commit()  # 每只抓完即提交：中断不丢已处理数据
        log.info("%s kline %d/%d code=%s ok=%d fail=%d", kind, idx, total, code, n_ok, n_fail)
        print(f"[{kind}-kline] {idx}/{total} {code} ok={n_ok} fail={n_fail} skip={n_skip}", flush=True)
    return n_ok, n_fail


def fetch_stock_kline(conn, freqs, adjusts, start, end, force=False, today=None,
                      incremental=False):
    """从 stock_info 表读全部 code，逐个抓 K 线（日/周/月 × 复权）。

    依赖 stock_info 表已由 `--update-stock-list` 填充；本命令不重新查询列表接口。
    支持断点续传（跳过 last_fetch_date==today 的股票）与请求超时失败继续。
    incremental=True 时为日常增量模式：起始日取每只证券在库中的最后 K 线日期，
    并按频率门控（daily 工作日 / weekly 周末或超 7 天 / monthly 月初或超 31 天）。
    结束后用不复权日 K 回填 stock_info 行情字段。
    返回 (n_ok, n_fail) 供调用方打印汇总。
    """
    n_ok, n_fail = _kline_fetch_loop(conn, "stock", "stock_info", freqs, adjusts,
                                     start, end, force, today, incremental)
    backfill_stock_info(conn)
    return n_ok, n_fail


def fetch_etf_kline(conn, freqs, adjusts, start, end, force=False, today=None,
                    incremental=False):
    """从 etf_info 表读全部 code，逐个抓 K 线（日/周/月 × 复权）。

    依赖 etf_info 表已由 `--update-etf-list` 填充；本命令不重新查询列表接口。
    支持断点续传（跳过 last_fetch_date==today 的 ETF）与请求超时失败继续。
    incremental=True 时为日常增量模式：起始日取每只证券在库中的最后 K 线日期，
    并按频率门控（daily 工作日 / weekly 周末或超 7 天 / monthly 月初或超 31 天）。
    结束后用不复权日 K 回填 etf_info 行情字段。
    返回 (n_ok, n_fail) 供调用方打印汇总。
    """
    n_ok, n_fail = _kline_fetch_loop(conn, "etf", "etf_info", freqs, adjusts,
                                     start, end, force, today, incremental)
    backfill_etf_info(conn)
    return n_ok, n_fail


class _DataParser(argparse.ArgumentParser):
    """带组合校验的解析器：--incremental 仅适用于 K 线全量抓取命令。"""

    def parse_args(self, args=None, namespace=None):
        ns = super().parse_args(args, namespace)
        if ns.incremental and not (ns.fetch_stock_kline or ns.fetch_etf_kline):
            self.error(
                "--incremental 只能与 --fetch-stock-kline / --fetch-etf-kline 一起使用"
            )
        return ns


def build_parser():
    """构造 CLI 参数解析器。--codes 与列表/K 线全量抓取选项互斥。"""
    parser = _DataParser(description="BaoStock 数据采集")
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
    group.add_argument("--fetch-stock-kline", action="store_true",
                       help="根据 stock_info 表全量抓取 A 股的日/周/月 K 线")
    parser.add_argument("--freq", default="daily",
                        help="逗号分隔频率: daily,weekly,monthly")
    parser.add_argument("--adjust", default=None,
                        help="逗号分隔复权: 2(前复权)/3(不复权)；"
                             "--codes 缺省 3，--fetch-etf-kline 缺省 2,3")
    parser.add_argument("--start", default=None, help="起始日期 YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="结束日期 YYYY-MM-DD")
    parser.add_argument("--list-date", default=None,
                        help="--update-etf-list 使用的日期 YYYY-MM-DD，默认今天")
    parser.add_argument("--force", action="store_true",
                       help="忽略 last_fetch_date 标记，强制全量重抓（供换日期窗口等场景）")
    parser.add_argument("--incremental", action="store_true",
                       help="日常增量更新：从每只证券最后一根 K 线日期开始抓，"
                            "并按频率门控（daily 仅工作日；weekly 周六/周日或"
                            "距今超 7 天；monthly 月初前 3 天或距今超 31 天）")
    parser.add_argument("--timeout", type=int, default=30,
                       help="网络请求超时秒数，0 禁用超时（默认 30）")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    conn = init_db(args.db)
    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"baostock login failed: {lg.error_code} {lg.error_msg}")
    if args.timeout and args.timeout > 0:
        # baostock 全局 socket 阻塞 recv 无超时是“卡住”的根源；login 后对其设
        # 超时，超时被 send_msg 捕获转成 error_code 返回，上层抛 RuntimeError
        # 记 fail 继续，不再无限挂起。超时后会话可能失效，靠重启+断点续传兜底。
        try:
            sock = bs.common.context.default_socket
            if sock is not None:
                sock.settimeout(args.timeout)
                log.info("set baostock socket timeout=%ss", args.timeout)
        except Exception:
            log.warning("failed to set socket timeout; continuing without it")
    try:
        if args.update_etf_list:
            list_date = args.list_date or date.today().isoformat()
            n_ok, n_fail = update_etf_list(conn, list_date)
            print(f"done. db={args.db} etf_list ok={n_ok} fail={n_fail} date={list_date}")
        elif args.update_stock_list:
            list_date = args.list_date or date.today().isoformat()
            n_ok, n_fail = update_stock_list(conn, list_date)
            print(f"done. db={args.db} stock_list ok={n_ok} fail={n_fail} date={list_date}")
        elif args.fetch_stock_kline:
            freqs = [f.strip() for f in args.freq.split(",") if f.strip()]
            # db-design.md：每张 K 线表同时保存 前复权(2) 与 不复权(3)；
            # --fetch-stock-kline 默认 2,3，可用 --adjust 覆盖。
            adjusts = ([a.strip() for a in args.adjust.split(",") if a.strip()]
                       if args.adjust else ["2", "3"])
            start, end = resolve_date_range(args.start, args.end)
            n_ok, n_fail = fetch_stock_kline(conn, freqs, adjusts, start, end,
                                              force=args.force,
                                              incremental=args.incremental)
            print(f"done. db={args.db} stock_kline ok={n_ok} fail={n_fail} "
                  f"freqs={freqs} adjusts={adjusts} start={start} end={end} "
                  f"force={args.force} incremental={args.incremental}")
        elif args.fetch_etf_kline:
            freqs = [f.strip() for f in args.freq.split(",") if f.strip()]
            # db-design.md：每张 K 线表同时保存 前复权(2) 与 不复权(3)；
            # --fetch-etf-kline 默认 2,3，可用 --adjust 覆盖。
            adjusts = ([a.strip() for a in args.adjust.split(",") if a.strip()]
                       if args.adjust else ["2", "3"])
            start, end = resolve_date_range(args.start, args.end)
            n_ok, n_fail = fetch_etf_kline(conn, freqs, adjusts, start, end,
                                            force=args.force,
                                            incremental=args.incremental)
            print(f"done. db={args.db} etf_kline ok={n_ok} fail={n_fail} "
                  f"freqs={freqs} adjusts={adjusts} start={start} end={end} "
                  f"force={args.force} incremental={args.incremental}")
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
