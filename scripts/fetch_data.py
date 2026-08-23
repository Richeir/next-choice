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
from db import (backfill_attempts, clear_backfill_attempts, fetched_today,
                init_db, insert_kline, kline_max_date, mark_fetched,
                record_backfill_attempt)
from transform import is_etf_code, kline_table, market_of

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _upsert_sql(table, cols):
    """生成 INSERT ... ON CONFLICT(code) DO UPDATE SET 语句。

    相比 INSERT OR REPLACE（删旧行再插新行，未列出的列会归 NULL），
    upsert 保留不在 cols 中的列（如雪球补齐的 full_name / high_52w 等）。"""
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "code")
    return (f"INSERT INTO {table} ({', '.join(cols)}) "
            f"VALUES ({', '.join('?' * len(cols))}) "
            f"ON CONFLICT(code) DO UPDATE SET {updates}")


# 新列表比库内在市数量少于该比例时判定为响应残缺，跳过退市标记：
# 一次截断的响应不该把全市场打成退市。
_DELIST_SANITY_RATIO = 0.5


def _mark_delisted(conn, table, live_codes, today):
    """把库内 status='1' 但不在最新列表里的证券标记为退市，返回标记数。

    上游列表只含在交易证券，缺席即已摘牌。不标记的话增量路径的
    delisted 跳过永不命中，退市股每轮都被重抓，白耗请求配额。
    """
    live = conn.execute(
        f"SELECT count(*) c FROM {table} WHERE status='1'").fetchone()["c"]
    if live and len(live_codes) < live * _DELIST_SANITY_RATIO:
        log.warning("%s: skip delisting sweep, fresh list has %d codes vs %d"
                    " live in db (looks like a truncated response)",
                    table, len(live_codes), live)
        return 0
    # 用临时表而非 NOT IN (?,?,...)：全市场 5000+ 只会撞上 SQLite 的
    # 绑定变量上限。
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS _live_codes"
                 " (code TEXT PRIMARY KEY)")
    conn.execute("DELETE FROM _live_codes")
    conn.executemany("INSERT OR IGNORE INTO _live_codes (code) VALUES (?)",
                     [(c,) for c in live_codes])
    n = conn.execute(
        f"UPDATE {table} SET status='0', outDate=COALESCE(outDate, ?)"
        " WHERE status='1' AND code NOT IN (SELECT code FROM _live_codes)",
        (today,)).rowcount
    conn.execute("DROP TABLE _live_codes")
    conn.commit()
    if n:
        log.info("%s: marked %d securities delisted", table, n)
    return n


def update_stock_list(conn, max_retries=3):
    """腾讯全市场刷新 stock_info：列表 + 行情字段（金额单位元）。

    type 恒 '1'；出现在列表里的置 status='1'，库内缺席的旧行标记退市。
    未知号段（如北交所 92 开头）跳过并计入返回值的第二位（skip），但仍算
    “在市”，不会被退市标记误伤。
    用 upsert 写库，保留雪球补齐的 full_name / industry / 52 周高低等列。
    返回 (n_ok, n_skip, n_delisted)。
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
    conn.commit()
    # 比对用全量列表（含被跳过的号段），避免把不入库的号段误判为退市
    n_delisted = _mark_delisted(conn, "stock_info",
                                {r["code"] for r in rows}, today)
    return n_ok, n_skip, n_delisted


def update_etf_list(conn, max_retries=3):
    """新浪列表 + 同花顺类别 + 新浪基金规模/管理人，刷新 etf_info。

    用 upsert 写库，保留雪球补齐的 high_52w / low_52w 与 K 线断点标记；
    库内缺席于最新列表的旧行标记退市。返回 (n_ok, n_fail, n_delisted)。
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
    conn.commit()
    n_delisted = _mark_delisted(conn, "etf_info", {e["code"] for e in etfs},
                                date.today().isoformat())
    return n_ok, n_fail, n_delisted


VALID_ADJUST = ("2", "3")
VALID_FREQ = ("daily", "weekly", "monthly")
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


# 增量窗口向前扩展的自然日数：窗口首行的 preclose=上一根 close，需要窗口前
# 至少一根历史；按自然日回退须容纳周末与长假（周线需覆盖前一个完整周，
# 月线需覆盖前一个完整月）。
_PAD = {"daily": 8, "weekly": 12, "monthly": 40}


def _pad_start(freq, base_start, full_start):
    """把抓取起点向前扩展以获取窗口首行的 preclose/pctChg 上下文。

    base_start 为真正的入库起点（_inc_fstart 对齐后的起点或 --start）；
    full_start 是全量抓取起点，其之前的历史本就不入库，扩展不越过它。
    """
    d = date.fromisoformat(base_start)
    pad = (d - timedelta(days=_PAD[freq])).isoformat()
    return pad if pad > full_start else full_start


def _period_start(d, freq):
    """日期 d 所属日历周期的起点（周一起始周 / 月 1 号）。"""
    if freq == "weekly":
        return d - timedelta(days=d.weekday())
    return d.replace(day=1)


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


def _fetch_daily_df(kind, code, adjustflag, start, end, max_retries):
    """按请求的复权方式抓一次日线原始序列（周/月由它本地派生）。

    数据源失败（返回 None）抛 RuntimeError 由主循环记 fail。
    """
    if kind == "etf":
        df = src.etf_kline(code, start, end, max_retries=max_retries)
    else:
        df = src.stock_kline(code, start, end,
                             adjust=_ADJUST_SINA[adjustflag],
                             max_retries=max_retries)
    if df is None:
        raise RuntimeError(f"{kind} kline {code} {adjustflag} fetch failed")
    return df


def _write_kline(conn, kind, code, freq, adjustflag, daily_df, start):
    """把日线序列按 freq 落库（周/月先本地重采样），只写 date >= start 的行。

    daily_df 覆盖的窗口比 start 更靠前，用于给窗口首行提供 preclose/pctChg
    上下文，多出来的行在这里丢弃，避免把重叠区已入库的正确值覆盖成 NULL。
    周/月在写入前删除本轮覆盖周期的旧行，防止"进行中周期"在不同日期
    抓取产生不同 date 的残留行堆积（同一周期出现多根 K）。
    """
    if daily_df.empty:
        return 0
    df = (src.resample_kline(daily_df, freq)
          if freq in ("weekly", "monthly") else daily_df)
    df = df[df["date"] >= start].reset_index(drop=True)
    if df.empty:
        return 0
    if freq in ("weekly", "monthly"):
        # 先插入（upsert 的 COALESCE 会保留已有的正确 pctChg）再删除，
        # 避免整段删除后重插导致扩展窗口覆盖不到时丢失 pctChg。
        table = kline_table(kind, freq)
        period_start = _period_start(date.fromisoformat(start),
                                     freq).isoformat()
        new_dates = [str(d) for d in df["date"]]
        marks = ",".join("?" for _ in new_dates)
        conn.execute(
            f"DELETE FROM {table} WHERE code=? AND adjustflag=? AND date>=?"
            f" AND date NOT IN ({marks})",
            [code, adjustflag, period_start] + new_dates)
    insert_kline(conn, kind, freq, adjustflag,
                 _kline_rows(kind, freq, df, code, adjustflag))
    return len(df)


def _fetch_code_klines(conn, kind, code, freqs, adjustflag, starts, end,
                       max_retries, full_start):
    """抓一次日线，派生出该 (code, adjustflag) 下的所有频率。

    周/月本就由日线重采样得到，按频率各请求一次日 K 是纯粹的重复开销：
    全市场 5000+ 只 × 2 档复权下，daily,weekly,monthly 能把约 3 万次
    请求压到 1 万次。

    starts: {freq: 入库起点}。抓取窗口取各频率扩展后的最早起点，窗口更宽
    只会让重采样多出几根被丢弃的历史周期，不影响入库结果。
    """
    fetch_start = min(_pad_start(f, starts[f], full_start) for f in freqs)
    daily_df = _fetch_daily_df(kind, code, adjustflag, fetch_start, end,
                               max_retries)
    for freq in freqs:
        _write_kline(conn, kind, code, freq, adjustflag, daily_df,
                     starts[freq])


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
    - 前复权（adj='2'）即使增量也从 --start 全量重刷：qfq 序列除权后
      整段平移，末几天增量会混用复权基准；不复权增量安全；
    - 抓取起点向前扩展窗口（见 _fetch_one_kline）以补全首行
      preclose/pctChg，周/月写入前清理本轮覆盖周期的旧行；
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
            fstarts = {f: (_inc_fstart(f, last_dates.get(f), start)
                           if incremental else start)
                       for f in loop_freqs}
            for adj in adjusts:
                # 前复权序列在除权除息后整段平移，增量重拉只取末几天
                # 会混用新旧复权基准（拼接处假跳空），必须全量重刷；
                # 不复权序列增量安全。
                starts = {f: (start if adj == "2" else fstarts[f])
                          for f in loop_freqs}
                _fetch_code_klines(conn, kind, code, loop_freqs, adj, starts,
                                   end, max_retries, start)
            try:
                _update_52w_from_kline(conn, kind, table, code, today)
            except Exception as e:  # 52w 回写失败不影响 K 线成功判定
                log.warning("kline %s 52w update failed: %s", code, e)
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


# info 补齐的最大尝试次数：数据源本就没有某只证券的字段时（雪球对部分
# 标的不返回全称 / 52 周高低），选取条件永远成立，不设上限会每轮把这些
# 证券全部重试一遍。--force 忽略该上限。
MAX_INFO_ATTEMPTS = 5


def _cap_by_attempts(conn, kind, codes, force):
    """滤掉已达尝试上限的 code（force 时不过滤）。"""
    if force:
        return codes
    attempts = backfill_attempts(conn, kind)
    kept = [c for c in codes if attempts.get(c, 0) < MAX_INFO_ATTEMPTS]
    n_capped = len(codes) - len(kept)
    if n_capped:
        log.info("%s_info: skip %d codes at attempt cap (%d), use --force"
                 " to retry them", kind, n_capped, MAX_INFO_ATTEMPTS)
    return kept


def fetch_stock_info(conn, limit=None, sleep_s=0.5, max_retries=3,
                     force=False):
    """雪球逐只补齐个股字段，仅处理 full_name 为空的在市股票；
    basic 与 quote 任一成功即写库（部分成功也入库），两者皆失败记 fail；
    单只意外异常（如脏数据）记 fail 继续。

    没补到 full_name（选取条件所看的字段）的证券累计尝试次数，达到
    MAX_INFO_ATTEMPTS 后不再重试，除非 force。
    """
    import time as _time
    rows = conn.execute(
        "SELECT code FROM stock_info"
        " WHERE status='1' AND (full_name IS NULL OR full_name='')"
        " ORDER BY code").fetchall()
    codes = _cap_by_attempts(conn, "stock", [r["code"] for r in rows], force)
    if limit is not None:
        codes = codes[:limit]
    today = date.today().isoformat()
    n_ok = n_fail = 0
    total = len(codes)
    for idx, code in enumerate(codes, 1):
        try:
            basic = src.stock_basic(code, max_retries=max_retries)
            quote = src.stock_quote(code, max_retries=max_retries)
        except Exception as e:  # 防御：单只意外异常不中断整体
            log.warning("stock_info %s unexpected error: %s", code, e)
            record_backfill_attempt(conn, "stock", code, today)
            n_fail += 1
            print(f"[stock-info] {idx}/{total} {code} ok={n_ok}"
                  f" fail={n_fail}", flush=True)
            continue
        if basic is None and quote is None:
            log.warning("stock_info %s: both xq calls failed", code)
            record_backfill_attempt(conn, "stock", code, today)
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
        # 计数只看 full_name：部分补齐（如只拿到 pb）下次仍会被选中，
        # 清零的话这只证券就永远在重试。
        if mapping["full_name"] is not None:
            clear_backfill_attempts(conn, "stock", code)
            conn.commit()
        else:
            log.warning("stock_info %s: no full_name from source", code)
            record_backfill_attempt(conn, "stock", code, today)
        n_ok += 1
        print(f"[stock-info] {idx}/{total} {code} ok={n_ok} fail={n_fail}",
              flush=True)
        if idx < total and sleep_s > 0:
            _time.sleep(sleep_s)
    return n_ok, n_fail


def fetch_etf_info(conn, limit=None, sleep_s=0.5, max_retries=3, force=False):
    """雪球逐只补齐 ETF 字段（high_52w/low_52w），仅处理 high_52w 为空的
    在市 ETF；quote 失败记 fail，单只意外异常记 fail 继续。

    没补到 high_52w 的证券累计尝试次数，达到 MAX_INFO_ATTEMPTS 后不再
    重试，除非 force。
    """
    import time as _time
    rows = conn.execute(
        "SELECT code FROM etf_info"
        " WHERE status='1' AND high_52w IS NULL"
        " ORDER BY code").fetchall()
    codes = _cap_by_attempts(conn, "etf", [r["code"] for r in rows], force)
    if limit is not None:
        codes = codes[:limit]
    today = date.today().isoformat()
    n_ok = n_fail = 0
    total = len(codes)
    for idx, code in enumerate(codes, 1):
        try:
            quote = src.stock_quote(code, max_retries=max_retries)
        except Exception as e:  # 防御：单只意外异常不中断整体
            log.warning("etf_info %s unexpected error: %s", code, e)
            record_backfill_attempt(conn, "etf", code, today)
            n_fail += 1
            print(f"[etf-info] {idx}/{total} {code} ok={n_ok} fail={n_fail}",
                  flush=True)
            continue
        if quote is None:
            log.warning("etf_info %s: xq quote failed", code)
            record_backfill_attempt(conn, "etf", code, today)
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
        if mapping["high_52w"] is not None:
            clear_backfill_attempts(conn, "etf", code)
            conn.commit()
        else:
            # quote 成功但无 52 周字段：计数 +1，达到上限后不再重试，
            # 避免数据源本就没有该字段的证券每轮都被扫一遍。
            log.warning("etf_info %s: quote ok but no 52w fields", code)
            record_backfill_attempt(conn, "etf", code, today)
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
        starts = {f: start for f in freqs}
        for adj in code_adjusts:
            _fetch_code_klines(conn, kind, code, freqs, adj, starts, end,
                               max_retries, start)
        _update_52w_from_kline(conn, kind, f"{kind}_info", code,
                               date.today().isoformat())
        conn.commit()
        print(f"[codes] {code} done ({kind})", flush=True)


class _DataParser(argparse.ArgumentParser):
    """带组合校验的解析器。

    --freq / --adjust 在这里就校验并解析成列表（freq_list / adjust_list）：
    留到抓取循环里才 KeyError 的话，`--adjust 1` / `--freq daly` 这类笔误
    要跑到深处才暴露，前面的请求配额已经白花了。
    """

    def parse_args(self, args=None, namespace=None):
        ns = super().parse_args(args, namespace)
        if ns.incremental and not (ns.fetch_stock_kline or ns.fetch_etf_kline):
            self.error(
                "--incremental 只能与 --fetch-stock-kline /"
                " --fetch-etf-kline 一起使用"
            )
        ns.freq_list = self._split_checked("--freq", ns.freq, VALID_FREQ)
        # --adjust 缺省值随命令不同（K 线全量 2,3；--codes 只有 3），
        # 留给 main 决定，这里只校验显式给出的值。
        ns.adjust_list = (self._split_checked("--adjust", ns.adjust,
                                              VALID_ADJUST)
                          if ns.adjust is not None else None)
        return ns

    def _split_checked(self, flag, raw, valid):
        items = [v.strip() for v in (raw or "").split(",") if v.strip()]
        if not items:
            self.error(f"{flag} 不能为空")
        bad = [v for v in items if v not in valid]
        if bad:
            self.error(f"{flag} 不支持 {','.join(bad)}；可选值："
                       f"{','.join(valid)}")
        return items


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
                       help="忽略 last_fetch_date 标记与 info 补齐尝试上限")
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
    # 没有 basicConfig 的话 log.info/warning 全部丢弃，出问题只剩 print 的
    # 进度行可看。LOG_LEVEL 可调（默认 INFO）。
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    conn = init_db(args.db)
    try:
        if args.update_stock_list:
            n_ok, n_skip, n_del = update_stock_list(conn, args.max_retries)
            print(f"done. db={args.db} stock_list ok={n_ok} skip={n_skip} "
                  f"delisted={n_del}")
        elif args.update_etf_list:
            n_ok, n_fail, n_del = update_etf_list(conn, args.max_retries)
            print(f"done. db={args.db} etf_list ok={n_ok} fail={n_fail} "
                  f"delisted={n_del}")
        elif args.fetch_stock_info:
            n_ok, n_fail = fetch_stock_info(conn, limit=args.limit,
                                            sleep_s=args.sleep,
                                            max_retries=args.max_retries,
                                            force=args.force)
            print(f"done. db={args.db} stock_info ok={n_ok} fail={n_fail}")
        elif args.fetch_etf_info:
            n_ok, n_fail = fetch_etf_info(conn, limit=args.limit,
                                          sleep_s=args.sleep,
                                          max_retries=args.max_retries,
                                          force=args.force)
            print(f"done. db={args.db} etf_info ok={n_ok} fail={n_fail}")
        elif args.fetch_stock_kline or args.fetch_etf_kline:
            freqs = args.freq_list
            adjusts = args.adjust_list or ["2", "3"]
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
            freqs = args.freq_list
            adjusts = args.adjust_list or ["3"]
            codes = [c.strip() for c in args.codes.split(",") if c.strip()]
            start, end = resolve_date_range(args.start, args.end)
            run_fetch(conn, codes, freqs, adjusts, start, end,
                      max_retries=args.max_retries)
            print(f"done. db={args.db} codes={codes} freqs={freqs}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
