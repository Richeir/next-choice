#!/usr/bin/env python3
"""Akshare 数据采集脚本（股票 / ETF 基础信息 + 日/周/月 K 线）。

用法示例：
    # 全量刷新 A 股列表 + 实时行情字段（腾讯源，一次拉全市场）
    python fetch_data.py --db data/market.db --update-stock-list

    # 全量刷新 ETF 列表 + 类别/规模/管理人
    python fetch_data.py --update-etf-list

    # 雪球逐只补齐个股字段（全称/行业/IPO/PB/52周高低），只处理未抓过的
    python fetch_data.py --fetch-stock-info [--limit 10]

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
from transform import market_of

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def update_stock_list(conn, max_retries=3):
    """腾讯全市场刷新 stock_info：列表 + 行情字段（金额单位元）。

    type 恒 '1'、status 恒 '1'（腾讯列表只含在交易证券；退市股旧行保留）。
    """
    rows = src.list_stocks(max_retries=max_retries)
    log.info("stock_zh_a_spot_tx -> %d stocks", len(rows))
    cols = ("code, code_name, market, type, status, last_trade_date,"
            " last_close, last_pct_chg, last_amount, pe_ttm, total_market_cap")
    sql = (f"INSERT OR REPLACE INTO stock_info ({cols}) "
           "VALUES (?,?,?,?,?,?,?,?,?,?,?)")
    today = date.today().isoformat()
    n_ok = 0
    total = len(rows)
    for idx, r in enumerate(rows, 1):
        conn.execute(sql, (r["code"], r["name"], market_of(r["code"]), "1",
                           "1", today, r["last_close"], r["last_pct_chg"],
                           r["last_amount"], r["pe_ttm"],
                           r["total_market_cap"]))
        n_ok += 1
        if idx % 500 == 0 or idx == total:
            conn.commit()
            print(f"[stock-list] {idx}/{total}", flush=True)
    return n_ok, 0


def update_etf_list(conn, max_retries=3):
    """新浪列表 + 同花顺类别 + 新浪基金规模/管理人，刷新 etf_info。"""
    etfs = src.list_etfs(max_retries=max_retries)
    cats = src.etf_category_map(max_retries=max_retries)
    scales = src.fund_scale_map(max_retries=max_retries)
    log.info("etf list=%d category=%d scale=%d",
             len(etfs), len(cats), len(scales))
    cols = ("code, code_name, market, type, status, ipoDate,"
            " category, manager, fund_scale")
    sql = f"INSERT OR REPLACE INTO etf_info ({cols}) VALUES (?,?,?,?,?,?,?,?,?)"
    n_ok = n_fail = 0
    total = len(etfs)
    for idx, e in enumerate(etfs, 1):
        s = scales.get(e["code"], {})
        try:
            conn.execute(sql, (e["code"], e["name"], market_of(e["code"]),
                               "5", "1", s.get("ipo_date"),
                               cats.get(e["code"]), s.get("manager"),
                               s.get("fund_scale")))
            n_ok += 1
        except Exception as ex:  # 防御：单只失败不中断
            log.warning("etf_info insert %s failed: %s", e["code"], ex)
            n_fail += 1
        if idx % 100 == 0 or idx == total:
            conn.commit()
            print(f"[etf-list] {idx}/{total} ok={n_ok} fail={n_fail}",
                  flush=True)
    return n_ok, n_fail


def build_parser():
    parser = argparse.ArgumentParser(description="Akshare 数据采集")
    parser.add_argument("--db", default=os.path.join(ROOT, "data", "market.db"))
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--update-stock-list", action="store_true",
                       help="腾讯全市场刷新 A 股列表与行情字段")
    group.add_argument("--update-etf-list", action="store_true",
                       help="刷新 ETF 列表/类别/规模/管理人")
    group.add_argument("--fetch-stock-info", action="store_true",
                       help="雪球逐只补齐个股字段（仅未抓过的）")
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
                        help="--fetch-stock-info 限制处理数量")
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
            n_ok, n_fail = update_stock_list(conn, args.max_retries)
            print(f"done. db={args.db} stock_list ok={n_ok} fail={n_fail}")
        elif args.update_etf_list:
            n_ok, n_fail = update_etf_list(conn, args.max_retries)
            print(f"done. db={args.db} etf_list ok={n_ok} fail={n_fail}")
        else:
            raise SystemExit("该命令将在后续任务实现")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
