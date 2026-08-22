#!/usr/bin/env python3
"""Akshare 数据采集脚本（股票 / ETF 基础信息 + 日/周/月 K 线）。

用法示例：
    # 全量刷新 A 股列表 + 实时行情字段（腾讯源，一次拉全市场）
    python fetch_data.py --db data/market.db --update-stock-list

    # 全量刷新 ETF 列表 + 类别/规模/管理人
    python fetch_data.py --update-etf-list

    # 雪球逐只补齐个股字段（全称/行业/IPO/PB/52周高低），只处理未抓过的
    python fetch_data.py --fetch-stock-info [--limit 10]

    # 雪球逐只补齐 ETF 字段（52周高低），只处理未抓过的
    python fetch_data.py --fetch-etf-info [--limit 10]

    # 按 info 表全量抓 K 线（周/月由日 K 本地重采样）
    python fetch_data.py --fetch-stock-kline --freq daily,weekly,monthly \
        --adjust 2,3 --start 2026-01-05

    # 日常增量
    python fetch_data.py --fetch-stock-kline --freq daily,weekly,monthly \
        --incremental

数据源（东财源在当前网络不可用，故全部使用非东财源）：
腾讯全市场行情 / 新浪日 K / 新浪+同花顺+新浪基金列表与规模 / 雪球个股信息。
详见 doc/akshare-api.md。
"""
import argparse
import logging
import os
import sys
from datetime import date, timedelta

log = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import akshare_source as src
from db import (fetched_today, init_db, insert_kline, kline_max_date,
                mark_fetched)
from transform import is_etf_code, market_of

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _upsert_sql(table, cols):
    """生成 INSERT ... ON CONFLICT(code) DO UPDATE SET 语句。

    相比 INSERT OR REPLACE（删旧行再插新行，未列出的列会归 NULL），
    upsert 保留不在 cols 中的列（如雪球补齐的 full_name / high_52w 等）。"""
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "code")
    return (f"INSERT INTO {table} ({', '.join(cols)}) "
            f"VALUES ({', '.join('?' * len(cols))}) "
            f"ON CONFLICT(code) DO UPDATE SET {updates}")


def update_stock_list(conn, max_retries=3):
    """腾讯全市场刷新 stock_info：列表 + 行情字段（金额单位元）。

    type 恒 '1'、status 恒 '1'（腾讯列表只含在交易证券；退市股旧行保留）。
    未知号段（如北交所 92 开头）跳过并计入返回值的第二位（skip）。
    用 upsert 写库，保留雪球补齐的 full_name / industry / 52 周高低等列。
    """
    rows = src.list_stocks(max_retries=max_retries)
    log.info("stock_zh_a_spot_tx -> %d stocks", len(rows))
    cols = ["code", "code_name", "market", "type", "status",
            "last_trade_date", "last_close", "last_pct_chg", "last_amount",
            "pe_ttm", "total_market_cap"]
    sql = _upsert_sql("stock_info", cols)
    today = date.today().isoformat()
    n_ok = n_skip = 0
    total = len(rows)
    for idx, r in enumerate(rows, 1):
        try:
            market = market_of(r["code"])
        except ValueError:
            # 未知号段（如北交所 92 开头）不在项目 SH/SZ 范围内，跳过
            log.warning("skip %s: unknown code segment", r["code"])
            n_skip += 1
            continue
        conn.execute(sql, [r["code"], r["name"], market, "1",
                           "1", today, r["last_close"], r["last_pct_chg"],
                           r["last_amount"], r["pe_ttm"],
                           r["total_market_cap"]])
        n_ok += 1
        if idx % 500 == 0 or idx == total:
            conn.commit()
            print(f"[stock-list] {idx}/{total} ok={n_ok} skip={n_skip}",
                  flush=True)
    return n_ok, n_skip


def update_etf_list(conn, max_retries=3):
    """新浪列表 + 同花顺类别 + 新浪基金规模/管理人，刷新 etf_info。

    用 upsert 写库，保留雪球补齐的 high_52w / low_52w 与 K 线断点标记。
    """
    etfs = src.list_etfs(max_retries=max_retries)
    cats = src.etf_category_map(max_retries=max_retries)
    scales = src.fund_scale_map(max_retries=max_retries)
    log.info("etf list=%d category=%d scale=%d",
             len(etfs), len(cats), len(scales))
    cols = ["code", "code_name", "market", "type", "status", "ipoDate",
            "category", "manager", "fund_scale"]
    sql = _upsert_sql("etf_info", cols)
    n_ok = n_fail = 0
    total = len(etfs)
    for idx, e in enumerate(etfs, 1):
        s = scales.get(e["code"], {})
        market = e.get("market")
        if market is None:
            try:
                market = market_of(e["code"])
            except ValueError:
                log.warning("skip %s: unknown code segment", e["code"])
                n_fail += 1
                continue
        try:
            conn.execute(sql, [e["code"], e["name"], market,
                               "5", "1", s.get("ipo_date"),
                               cats.get(e["code"]), s.get("manager"),
                               s.get("fund_scale")])
            n_ok += 1
        except Exception as ex:  # 防御：单只失败不中断
            log.warning("etf_info insert %s failed: %s", e["code"], ex)
            n_fail += 1
        if idx % 100 == 0 or idx == total:
            conn.commit()
            print(f"[etf-list] {idx}/{total} ok={n_ok} fail={n_fail}",
                  flush=True)
    return n_ok, n_fail


VALID_ADJUST = ("2", "3")
_ADJUST_SINA = {"3": "", "2": "qfq"}
# 日 K 增量重拉 1 天覆盖修正；周/月的回溯起点在 _inc_fstart 中对齐周期边界


def _inc_fstart(freq, base_date, fallback):
    """增量模式的抓取起点（base_date 为该频率最后一根 K 线日期，无则 fallback）。

    周/月频率必须对齐到周期边界，否则重采样会用不完整周期覆盖已入库的完整周/月 K：
    - weekly：回退到 base 所在周的前一周周一；
    - monthly：回退到 base 所在月的前一个月 1 号；
    - daily：回退 1 天覆盖修正。
    """
    if base_date is None:
        return fallback
    d = date.fromisoformat(base_date)
    if freq == "weekly":
        prev_week_start = d - timedelta(days=d.weekday() + 7)
        return prev_week_start.isoformat()
    if freq == "monthly":
        first_of_this_month = d.replace(day=1)
        first_of_prev = (first_of_this_month - timedelta(days=1)).replace(day=1)
        return first_of_prev.isoformat()
    return (d - timedelta(days=1)).isoformat()


def _due_freqs(freqs, today, last_dates):
    """增量模式频率门控：
    daily 仅工作日；weekly 周末且最后周 K 距今 >2 天，或距今 >7 天（补漏）；
    monthly 月初前 3 天（day<=3），或距今 >31 天（补漏）。
    last_dates: {freq: 'YYYY-MM-DD' 或 None}，None 不门控直接拉。
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
            gap = (today - date.fromisoformat(last)).days
            if (today.weekday() >= 5 and gap > 2) or gap > 7:
                due.append(f)
        elif f == "monthly":
            if today.day <= 3 or (today - date.fromisoformat(last)).days > 31:
                due.append(f)
    return due


def _kline_rows(kind, freq, df, code, adjustflag):
    """KLINE_COLS DataFrame -> db.insert_kline 的行列表（列顺序对齐
    db._TABLE_COLS；weekly/monthly 表无 preclose 列，多余键自动忽略）。"""
    from db import _TABLE_COLS
    cols = _TABLE_COLS[(kind, freq)]
    daily = freq == "daily"
    out = []
    for _, r in df.iterrows():
        vals = {"date": r["date"], "code": code, "open": r["open"],
                "high": r["high"], "low": r["low"], "close": r["close"],
                "volume": r["volume"], "amount": r["amount"],
                "adjustflag": adjustflag, "turn": r["turn"],
                "pctChg": r["pctChg"]}
        if daily:
            vals.update({"preclose": r["preclose"], "tradestatus": "1",
                         "isST": "0"})
            if kind == "etf":  # 新数据源无估值列
                vals.update({"peTTM": None, "pbMRQ": None, "psTTM": None,
                             "pcfNcfTTM": None})
        out.append([vals.get(c) for c in cols])
    return out


def _fetch_one_kline(conn, kind, code, freq, adjustflag, start, end,
                     max_retries):
    """抓单只 (code, freq, adjustflag)：日 K 来自数据源，周/月本地重采样。
    数据源失败（返回 None）抛 RuntimeError 由主循环记 fail。"""
    if kind == "etf":
        df = src.etf_kline(code, start, end, max_retries=max_retries)
    else:
        df = src.stock_kline(code, start, end,
                             adjust=_ADJUST_SINA[adjustflag],
                             max_retries=max_retries)
    if df is None:
        raise RuntimeError(f"{kind} kline {code} {adjustflag} fetch failed")
    if df.empty:
        return 0
    if freq in ("weekly", "monthly"):
        df = src.resample_kline(df, freq)
    insert_kline(conn, kind, freq, adjustflag,
                 _kline_rows(kind, freq, df, code, adjustflag))
    return len(df)


# 52 周高低重算：窗口长度与覆盖容差（容纳周末/长假缺口）
_52W_WINDOW_DAYS = 365
_52W_COVER_TOL_DAYS = 15


def _update_52w_from_kline(conn, kind, info_table, code, today):
    """用不复权日 K 重算最近 52 周最高/最低并回写 info 表。

    仅当 K 线覆盖达到窗口（允许 _52W_COVER_TOL_DAYS 天缺口）时回写，
    否则保留原值（如雪球补齐值），避免部分窗口算出错误值。
    """
    from transform import kline_table
    table = kline_table(kind, "daily")
    today_dt = date.fromisoformat(today)
    win_start = (today_dt - timedelta(days=_52W_WINDOW_DAYS)).isoformat()
    cover_limit = (today_dt
                   - timedelta(days=_52W_WINDOW_DAYS - _52W_COVER_TOL_DAYS)
                   ).isoformat()
    row = conn.execute(
        f"SELECT max(high) hi, min(low) lo FROM {table}"
        " WHERE code=? AND adjustflag='3' AND date>=?",
        (code, win_start)).fetchone()
    if row["hi"] is None or row["lo"] is None:
        return
    min_date = conn.execute(
        f"SELECT min(date) FROM {table}"
        " WHERE code=? AND adjustflag='3'", (code,)).fetchone()[0]
    if min_date is None or min_date > cover_limit:
        return
    conn.execute(f"UPDATE {info_table} SET high_52w=?, low_52w=?"
                 " WHERE code=?", (row["hi"], row["lo"], code))


def _kline_fetch_loop(conn, kind, table, freqs, adjusts, start, end, force,
                      today, sleep_s, max_retries, incremental=False):
    """K 线抓取主循环（股票/ETF 共用）。

    - 断点续传：非 force 跳过 last_fetch_date==today 的证券；
    - 增量：按 _due_freqs 门控，起始日取该频率最后一根日期往前回退
      _INC_PAD_DAYS（保证周/月重采样周期完整）；退市（status='0'）跳过；
    - 标记：全量需三档全集成功；增量只需本轮应更频率全部成功；
    - 每只抓完即提交；单只失败记 warning 不中断。
    """
    import time as _time
    today = today or date.today().isoformat()
    today_dt = date.fromisoformat(today)
    fullset = set(freqs) == {"daily", "weekly", "monthly"}
    rows = conn.execute(f"SELECT code, status FROM {table}").fetchall()
    codes = [r["code"] for r in rows]
    delisted = ({r["code"] for r in rows if r["status"] == "0"}
                if incremental else set())
    done = set() if force else fetched_today(conn, kind, today)
    max_dates = ({f: kline_max_date(conn, kind, f) for f in freqs}
                 if incremental else {})
    n_ok = n_fail = n_skip = 0
    total = len(codes)
    for idx, code in enumerate(codes, 1):
        tag = f"[{kind}-kline] {idx}/{total} {code}"
        if code in done:
            n_skip += 1
            print(f"{tag} skip(fetched) ok={n_ok} fail={n_fail} skip={n_skip}",
                  flush=True)
            continue
        if code in delisted:
            n_skip += 1
            print(f"{tag} skip(delisted) ok={n_ok} fail={n_fail} skip={n_skip}",
                  flush=True)
            continue
        if incremental:
            last_dates = {f: max_dates[f].get(code) for f in freqs}
            loop_freqs = _due_freqs(freqs, today_dt, last_dates)
            if not loop_freqs:
                n_skip += 1
                print(f"{tag} skip(not due) ok={n_ok} fail={n_fail} "
                      f"skip={n_skip}", flush=True)
                continue
        else:
            last_dates = {}
            loop_freqs = freqs
        success = True
        try:
            for freq in loop_freqs:
                fstart = _inc_fstart(freq, last_dates.get(freq), start) \
                    if incremental else start
                for adj in adjusts:
                    _fetch_one_kline(conn, kind, code, freq, adj, fstart, end,
                                     max_retries)
            _update_52w_from_kline(conn, kind, table, code, today)
            n_ok += 1
        except Exception as e:  # 网络/解析/入库失败均记 fail 继续
            log.warning("kline %s failed: %s", code, e)
            n_fail += 1
            success = False
        if success and (incremental or fullset):
            mark_fetched(conn, kind, code, today)
        conn.commit()
        print(f"{tag} ok={n_ok} fail={n_fail} skip={n_skip}", flush=True)
        if idx < total and sleep_s > 0:
            _time.sleep(sleep_s)
    return n_ok, n_fail


def fetch_stock_kline(conn, freqs, adjusts, start, end, force=False,
                      today=None, incremental=False, sleep_s=0.5,
                      max_retries=3):
    """按 stock_info 全表抓 A 股 K 线（周/月由日 K 重采样）。"""
    return _kline_fetch_loop(conn, "stock", "stock_info", freqs, adjusts,
                             start, end, force, today, sleep_s, max_retries,
                             incremental)


def fetch_etf_kline(conn, freqs, adjusts, start, end, force=False,
                    today=None, incremental=False, sleep_s=0.5,
                    max_retries=3):
    """按 etf_info 全表抓 ETF K 线（仅不复权，adjusts 强制 ['3']）。"""
    if set(adjusts) != {"3"}:
        log.warning("ETF 仅支持不复权，--adjust %s 被强制为 ['3']", adjusts)
        adjusts = ["3"]
    return _kline_fetch_loop(conn, "etf", "etf_info", freqs, adjusts,
                             start, end, force, today, sleep_s, max_retries,
                             incremental)


def fetch_stock_info(conn, limit=None, sleep_s=0.5, max_retries=3):
    """雪球逐只补齐个股字段，仅处理 full_name 为空的在市股票；
    basic 与 quote 任一成功即写库（部分成功也入库），两者皆失败记 fail；
    单只意外异常（如脏数据）记 fail 继续。"""
    import time as _time
    rows = conn.execute(
        "SELECT code FROM stock_info"
        " WHERE status='1' AND (full_name IS NULL OR full_name='')"
        " ORDER BY code").fetchall()
    codes = [r["code"] for r in rows]
    if limit is not None:
        codes = codes[:limit]
    n_ok = n_fail = 0
    total = len(codes)
    for idx, code in enumerate(codes, 1):
        try:
            basic = src.stock_basic(code, max_retries=max_retries)
            quote = src.stock_quote(code, max_retries=max_retries)
        except Exception as e:  # 防御：单只意外异常不中断整体
            log.warning("stock_info %s unexpected error: %s", code, e)
            n_fail += 1
            print(f"[stock-info] {idx}/{total} {code} ok={n_ok}"
                  f" fail={n_fail}", flush=True)
            continue
        if basic is None and quote is None:
            log.warning("stock_info %s: both xq calls failed", code)
            n_fail += 1
            print(f"[stock-info] {idx}/{total} {code} ok={n_ok}"
                  f" fail={n_fail}", flush=True)
            continue
        basic = basic or {}
        quote = quote or {}
        mapping = {"full_name": basic.get("full_name"),
                   "industry": basic.get("industry"),
                   "ipoDate": basic.get("ipo_date"),
                   "pb": quote.get("pb"), "high_52w": quote.get("high_52w"),
                   "low_52w": quote.get("low_52w"),
                   "total_market_cap": quote.get("total_market_cap")}
        sets, vals = [], []
        for col, v in mapping.items():
            if v is not None:
                sets.append(f"{col}=?")
                vals.append(v)
        if sets:
            vals.append(code)
            conn.execute(f"UPDATE stock_info SET {', '.join(sets)}"
                         " WHERE code=?", vals)
            conn.commit()
        n_ok += 1
        print(f"[stock-info] {idx}/{total} {code} ok={n_ok} fail={n_fail}",
              flush=True)
        if idx < total and sleep_s > 0:
            _time.sleep(sleep_s)
    return n_ok, n_fail


def fetch_etf_info(conn, limit=None, sleep_s=0.5, max_retries=3):
    """雪球逐只补齐 ETF 字段（high_52w/low_52w），仅处理 high_52w 为空的
    在市 ETF；quote 失败记 fail，单只意外异常记 fail 继续。"""
    import time as _time
    rows = conn.execute(
        "SELECT code FROM etf_info"
        " WHERE status='1' AND high_52w IS NULL"
        " ORDER BY code").fetchall()
    codes = [r["code"] for r in rows]
    if limit is not None:
        codes = codes[:limit]
    n_ok = n_fail = 0
    total = len(codes)
    for idx, code in enumerate(codes, 1):
        try:
            quote = src.stock_quote(code, max_retries=max_retries)
        except Exception as e:  # 防御：单只意外异常不中断整体
            log.warning("etf_info %s unexpected error: %s", code, e)
            n_fail += 1
            print(f"[etf-info] {idx}/{total} {code} ok={n_ok} fail={n_fail}",
                  flush=True)
            continue
        if quote is None:
            log.warning("etf_info %s: xq quote failed", code)
            n_fail += 1
            print(f"[etf-info] {idx}/{total} {code} ok={n_ok} fail={n_fail}",
                  flush=True)
            continue
        mapping = {"high_52w": quote.get("high_52w"),
                   "low_52w": quote.get("low_52w")}
        sets, vals = [], []
        for col, v in mapping.items():
            if v is not None:
                sets.append(f"{col}=?")
                vals.append(v)
        if sets:
            vals.append(code)
            conn.execute(f"UPDATE etf_info SET {', '.join(sets)}"
                         " WHERE code=?", vals)
            conn.commit()
        else:
            # quote 成功但无 52 周字段：记 ok 不写库，下次运行会重试该只，
            # 显式日志便于观察哪些证券长期处于待补齐状态。
            log.warning("etf_info %s: quote ok but no 52w fields,"
                        " will retry next run", code)
        n_ok += 1
        print(f"[etf-info] {idx}/{total} {code} ok={n_ok} fail={n_fail}",
              flush=True)
        if idx < total and sleep_s > 0:
            _time.sleep(sleep_s)
    return n_ok, n_fail


def _ensure_info_row(conn, code, max_retries):
    """--codes 路径：若 info 表无该 code，按号段判断股票/ETF 写入最小行。"""
    exists = conn.execute("SELECT 1 FROM stock_info WHERE code=?",
                          (code,)).fetchone()
    if exists:
        return "stock"
    exists = conn.execute("SELECT 1 FROM etf_info WHERE code=?",
                          (code,)).fetchone()
    if exists:
        return "etf"
    if is_etf_code(code):
        conn.execute("INSERT INTO etf_info (code, market, type, status)"
                     " VALUES (?,?,?,?)",
                     (code, market_of(code), "5", "1"))
        return "etf"
    basic = src.stock_basic(code, max_retries=max_retries) or {}
    conn.execute("INSERT INTO stock_info (code, code_name, market, type,"
                 " status, full_name, industry, ipoDate)"
                 " VALUES (?,?,?,?,?,?,?,?)",
                 (code, basic.get("full_name"), market_of(code), "1", "1",
                  basic.get("full_name"), basic.get("industry"),
                  basic.get("ipo_date")))
    return "stock"


def run_fetch(conn, codes, freqs, adjusts, start, end, max_retries=3):
    """--codes 路径：补齐 info 行 + 逐只抓 K 线。"""
    for code in codes:
        kind = _ensure_info_row(conn, code, max_retries)
        conn.commit()
        code_adjusts = ["3"] if kind == "etf" else adjusts
        for freq in freqs:
            for adj in code_adjusts:
                _fetch_one_kline(conn, kind, code, freq, adj, start, end,
                                 max_retries)
        _update_52w_from_kline(conn, kind, f"{kind}_info", code,
                               date.today().isoformat())
        print(f"[codes] {code} done ({kind})", flush=True)


class _DataParser(argparse.ArgumentParser):
    """带组合校验的解析器：--incremental 仅适用于 K 线全量抓取命令。"""

    def parse_args(self, args=None, namespace=None):
        ns = super().parse_args(args, namespace)
        if ns.incremental and not (ns.fetch_stock_kline or ns.fetch_etf_kline):
            self.error(
                "--incremental 只能与 --fetch-stock-kline /"
                " --fetch-etf-kline 一起使用"
            )
        return ns


def build_parser():
    parser = _DataParser(description="Akshare 数据采集")
    parser.add_argument("--db", default=os.path.join(ROOT, "data", "market.db"))
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--update-stock-list", action="store_true",
                       help="腾讯全市场刷新 A 股列表与行情字段")
    group.add_argument("--update-etf-list", action="store_true",
                       help="刷新 ETF 列表/类别/规模/管理人")
    group.add_argument("--fetch-stock-info", action="store_true",
                       help="雪球逐只补齐个股字段（仅未抓过的）")
    group.add_argument("--fetch-etf-info", action="store_true",
                       help="雪球逐只补齐 ETF 52周高低（仅未抓过的）")
    group.add_argument("--fetch-stock-kline", action="store_true",
                       help="按 stock_info 全量抓 A 股 K 线")
    group.add_argument("--fetch-etf-kline", action="store_true",
                       help="按 etf_info 全量抓 ETF K 线（仅不复权）")
    group.add_argument("--codes",
                       help="逗号分隔的 6 位代码，如 600000,510050")
    parser.add_argument("--freq", default="daily",
                        help="逗号分隔频率: daily,weekly,monthly")
    parser.add_argument("--adjust", default=None,
                        help="逗号分隔复权: 2(前复权)/3(不复权)，缺省 2,3；"
                             "ETF 恒为 3")
    parser.add_argument("--start", default=None, help="起始日期 YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="结束日期 YYYY-MM-DD")
    parser.add_argument("--limit", type=int, default=None,
                        help="--fetch-stock-info / --fetch-etf-info"
                             " 限制处理数量")
    parser.add_argument("--sleep", type=float, default=0.5,
                        help="逐只抓取的间隔秒数（默认 0.5）")
    parser.add_argument("--max-retries", type=int, default=3,
                        help="网络请求最大重试次数（默认 3）")
    parser.add_argument("--force", action="store_true",
                       help="忽略 last_fetch_date 标记")
    parser.add_argument("--incremental", action="store_true",
                       help="日常增量：从最后一根 K 线日期起按频率门控抓取")
    return parser


def resolve_date_range(start, end, years=5):
    """未指定时默认回溯 5 年；end 缺省今天。"""
    if end is None:
        end = date.today().isoformat()
    if start is None:
        start = (date.fromisoformat(end)
                 - timedelta(days=365 * years)).isoformat()
    return start, end


def main(argv=None):
    args = build_parser().parse_args(argv)
    conn = init_db(args.db)
    try:
        if args.update_stock_list:
            n_ok, n_skip = update_stock_list(conn, args.max_retries)
            print(f"done. db={args.db} stock_list ok={n_ok} skip={n_skip}")
        elif args.update_etf_list:
            n_ok, n_fail = update_etf_list(conn, args.max_retries)
            print(f"done. db={args.db} etf_list ok={n_ok} fail={n_fail}")
        elif args.fetch_stock_info:
            n_ok, n_fail = fetch_stock_info(conn, limit=args.limit,
                                            sleep_s=args.sleep,
                                            max_retries=args.max_retries)
            print(f"done. db={args.db} stock_info ok={n_ok} fail={n_fail}")
        elif args.fetch_etf_info:
            n_ok, n_fail = fetch_etf_info(conn, limit=args.limit,
                                          sleep_s=args.sleep,
                                          max_retries=args.max_retries)
            print(f"done. db={args.db} etf_info ok={n_ok} fail={n_fail}")
        elif args.fetch_stock_kline or args.fetch_etf_kline:
            freqs = [f.strip() for f in args.freq.split(",") if f.strip()]
            adjusts = ([a.strip() for a in args.adjust.split(",") if a.strip()]
                       if args.adjust else ["2", "3"])
            start, end = resolve_date_range(args.start, args.end)
            if args.fetch_stock_kline:
                n_ok, n_fail = fetch_stock_kline(
                    conn, freqs, adjusts, start, end, force=args.force,
                    incremental=args.incremental, sleep_s=args.sleep,
                    max_retries=args.max_retries)
                kind = "stock"
            else:
                n_ok, n_fail = fetch_etf_kline(
                    conn, freqs, adjusts, start, end, force=args.force,
                    incremental=args.incremental, sleep_s=args.sleep,
                    max_retries=args.max_retries)
                kind = "etf"
            print(f"done. db={args.db} {kind}_kline ok={n_ok} fail={n_fail} "
                  f"freqs={freqs} start={start} end={end} "
                  f"force={args.force} incremental={args.incremental}")
        else:  # --codes
            freqs = [f.strip() for f in args.freq.split(",") if f.strip()]
            adjusts = ([a.strip() for a in args.adjust.split(",") if a.strip()]
                       if args.adjust else ["3"])
            codes = [c.strip() for c in args.codes.split(",") if c.strip()]
            start, end = resolve_date_range(args.start, args.end)
            run_fetch(conn, codes, freqs, adjusts, start, end,
                      max_retries=args.max_retries)
            print(f"done. db={args.db} codes={codes} freqs={freqs}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
