"""Akshare 数据源层：封装抓取、重试限速、格式转换（不感知 SQLite）。

已知限制（2026-08-22 实测）：
- 东财（*_em）系接口在当前网络不可用，本模块只用腾讯/新浪/雪球/同花顺源
- 新浪不支持 ETF 复权；雪球个股接口需逐只调用
"""
import logging
import time

import akshare as ak
import pandas as pd
import requests

from transform import market_of

log = logging.getLogger(__name__)


def to_sina_code(code):
    """600000 -> sh600000（新浪 K 线接口格式）。"""
    return market_of(code).lower() + code


def to_xq_code(code):
    """600000 -> SH600000（雪球接口格式）。"""
    return market_of(code) + code


def strip_prefix(prefixed):
    """sh600000 -> 600000。"""
    return prefixed[2:]


def yi_to_yuan(v):
    """亿 -> 元；None 透传。"""
    return None if v is None else float(v) * 1e8


def wan_to_yuan(v):
    """万 -> 元；None 透传。"""
    return None if v is None else float(v) * 1e4


def fetch_with_retry(fn, *args, max_retries=3, base_delay=1.0, sleep=time.sleep,
                     **kwargs):
    """调用 fn，网络异常（requests.RequestException）指数退避重试；
    其他异常直接抛出。退避时长：base_delay * 4**attempt（1s/4s/16s...）。"""
    last = None
    for attempt in range(max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except requests.exceptions.RequestException as e:
            last = e
            if attempt >= max_retries:
                break
            delay = base_delay * (4 ** attempt)
            log.warning("retry %d/%d after %ss: %s", attempt + 1,
                        max_retries, delay, e)
            sleep(delay)
    raise last


KLINE_COLS = ["date", "open", "high", "low", "close", "preclose",
              "volume", "amount", "turn", "pctChg"]


def _normalize_daily(df, turn_col=None, prevclose_col=None):
    """原始日 K 规整为 KLINE_COLS：preclose（prevclose_col 或上一根 close，
    首根 NaN）、pctChg=(close/preclose-1)*100、turn（无则 NaN）。"""
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df = df.sort_values("date").reset_index(drop=True)
    for c in ("open", "high", "low", "close", "volume", "amount"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    if prevclose_col:
        df["preclose"] = pd.to_numeric(df[prevclose_col], errors="coerce")
    else:
        df["preclose"] = df["close"].shift(1)
    df["pctChg"] = ((df["close"] - df["preclose"]) / df["preclose"]) * 100
    if turn_col and turn_col in df.columns:
        df["turn"] = pd.to_numeric(df[turn_col], errors="coerce")
    else:
        df["turn"] = float("nan")
    return df[KLINE_COLS]


def stock_kline(code, start, end, adjust="", max_retries=3):
    """新浪日 K（股票）。adjust: ''/qfq/hfq。失败返回 None。"""
    try:
        raw = fetch_with_retry(
            ak.stock_zh_a_daily, symbol=to_sina_code(code),
            start_date=start.replace("-", ""), end_date=end.replace("-", ""),
            adjust=adjust, max_retries=max_retries)
    except Exception as e:
        log.warning("stock_kline %s failed: %s", code, e)
        return None
    df = _normalize_daily(raw, turn_col="turnover")
    return df[(df["date"] >= start) & (df["date"] <= end)].reset_index(drop=True)


def etf_kline(code, start, end, max_retries=3):
    """新浪日 K（ETF，仅不复权；接口返回全量历史，本地按日期过滤）。"""
    try:
        raw = fetch_with_retry(ak.fund_etf_hist_sina,
                               symbol=to_sina_code(code),
                               max_retries=max_retries)
    except Exception as e:
        log.warning("etf_kline %s failed: %s", code, e)
        return None
    df = _normalize_daily(raw, prevclose_col="prevclose")
    return df[(df["date"] >= start) & (df["date"] <= end)].reset_index(drop=True)


def resample_kline(df, freq):
    """日 K -> 周/月 K。date 取组内最后交易日；turn 置 NaN。"""
    if freq not in ("weekly", "monthly"):
        raise ValueError(f"resample freq must be weekly/monthly, got {freq!r}")
    d = df.copy()
    d["_g"] = pd.to_datetime(d["date"]).dt.to_period(
        "W" if freq == "weekly" else "M")
    agg = d.groupby("_g").agg(
        date=("date", "max"), open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"),
        volume=("volume", "sum"), amount=("amount", "sum"))
    agg = agg.sort_values("date").reset_index(drop=True)
    agg["preclose"] = agg["close"].shift(1)
    agg["pctChg"] = ((agg["close"] - agg["preclose"]) / agg["preclose"]) * 100
    agg["turn"] = float("nan")
    return agg[KLINE_COLS]
