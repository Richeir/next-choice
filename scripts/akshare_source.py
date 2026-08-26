"""Akshare 数据源层：封装抓取、重试限速、格式转换（不感知 SQLite）。

已知限制（2026-08-22 实测）：
- 东财（*_em）系接口在当前网络不可用，本模块只用腾讯/新浪/雪球/同花顺源
- 新浪不支持 ETF 复权；雪球个股接口需逐只调用
"""
import json
import logging
import os
import random
import time

import akshare as ak
import pandas as pd
import requests

from transform import market_of

log = logging.getLogger(__name__)

# 可重试的异常：上游限流未必以 HTTP 错误出现——返回空体或异常结构时，
# akshare 的解析会抛 JSONDecodeError / KeyError / IndexError，这些同样是
# “重试一次多半就好”的瞬时故障，不该直接记 fail 丢掉这只证券。
_RETRYABLE = (
    requests.exceptions.RequestException,
    json.JSONDecodeError,  # ValueError 子类
    KeyError,
    IndexError,
)


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
                     jitter=random.random,
                     **kwargs):
    """调用 fn，瞬时故障（见 _RETRYABLE）指数退避重试；其他异常直接抛出。

    退避时长 base_delay * 4**attempt，再乘 1 + 0.5*jitter() 的随机抖动，
    避免全市场循环里成千上万只证券齐步重试、把限流放大。"""
    last = None
    for attempt in range(max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except _RETRYABLE as e:
            last = e
            if attempt >= max_retries:
                break
            delay = base_delay * (4 ** attempt) * (1 + 0.5 * jitter())
            log.warning("retry %d/%d after %.2fs: %s: %s", attempt + 1,
                        max_retries, delay, type(e).__name__, e)
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
    if prevclose_col and prevclose_col in df.columns:
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


from datetime import datetime, timedelta, timezone

_CST = timezone(timedelta(hours=8))


def list_stocks(max_retries=3):
    """腾讯全市场 A 股实时行情 -> 标准化 dict 列表。
    失败抛异常：列表是全量刷新的前提，不应静默降级。"""
    df = fetch_with_retry(ak.stock_zh_a_spot_tx, max_retries=max_retries)
    out = []
    for _, r in df.iterrows():
        out.append({
            "code": strip_prefix(r["code"]),
            "name": r["name"],
            "pe_ttm": float(r["pe_ttm"]) if pd.notna(r["pe_ttm"]) else None,
            "total_market_cap": yi_to_yuan(r["zsz"]),
            "last_close": float(r["zxj"]) if pd.notna(r["zxj"]) else None,
            "last_pct_chg": float(r["zdf"]) if pd.notna(r["zdf"]) else None,
            "last_amount": wan_to_yuan(r["turnover"]),
        })
    return out


def list_etfs(max_retries=3):
    """新浪 ETF 列表。`代码` 列带小写前缀（如 sz159998），剥离后作为 code；
    前缀同时给出市场（'SH'/'SZ'，新号段不依赖号段规则）；无前缀时 market 为 None。"""
    df = fetch_with_retry(ak.fund_etf_category_sina, symbol="ETF基金",
                          max_retries=max_retries)
    out = []
    for _, r in df.iterrows():
        raw = str(r["代码"])
        if raw[:2] in ("sh", "sz"):
            out.append({"code": raw[2:], "name": r["名称"],
                        "market": "SH" if raw[:2] == "sh" else "SZ"})
        else:
            out.append({"code": raw, "name": r["名称"], "market": None})
    return out


def etf_category_map(max_retries=3):
    """同花顺 ETF 类别：code -> 基金类型。"""
    df = fetch_with_retry(ak.fund_etf_category_ths, symbol="ETF基金",
                          max_retries=max_retries)
    return {str(r["基金代码"]): r["基金类型"] for _, r in df.iterrows()}


def fund_scale_map(max_retries=3):
    """新浪开放式基金规模表：code -> {fund_scale(元), manager, ipo_date}。
    该表覆盖全部开放式基金（含 ETF），多余条目由调用方按列表过滤。"""
    df = fetch_with_retry(ak.fund_scale_open_sina, max_retries=max_retries)
    out = {}
    for _, r in df.iterrows():
        est = str(r["成立日期"])[:10] if pd.notna(r["成立日期"]) else None
        out[str(r["基金代码"])] = {
            "fund_scale": wan_to_yuan(r["总募集规模"]),
            "manager": r["基金经理"] if pd.notna(r["基金经理"]) else None,
            "ipo_date": est,
        }
    return out


def xq_token():
    """XQ_TOKEN 环境变量 -> 雪球 xq_a_token；未配置或空白返回 None。

    akshare 内置 token 已过期（2026-08 实测，error 400016），需从浏览器
    登录雪球后拷贝有效 cookie 里的 xq_a_token 注入，--fetch-stock-info /
    --fetch-etf-info 才能工作。"""
    tok = os.environ.get("XQ_TOKEN", "").strip()
    return tok or None


_token_hint_shown = False


def _xq_fetch_failed(code, e):
    """记录雪球调用失败；首次失败时附带一次 token 配置提示，避免刷屏。"""
    global _token_hint_shown
    hint = ""
    if not _token_hint_shown:
        _token_hint_shown = True
        hint = ("（akshare 内置 xq_a_token 已失效：请从浏览器登录雪球后"
                "将 cookie 里的 xq_a_token 写入环境变量 XQ_TOKEN）"
                if xq_token() is None
                else "（已注入 XQ_TOKEN，若持续 400016 说明该 token 也已过期）")
    log.warning("xq fetch %s failed: %s%s", code, e, hint)


def _xq_kv(fetch_fn, code, max_retries):
    """雪球 item/value 两列 DataFrame -> dict。失败返回 None。"""
    try:
        df = fetch_with_retry(fetch_fn, symbol=to_xq_code(code),
                              token=xq_token(), max_retries=max_retries)
    except Exception as e:
        _xq_fetch_failed(code, e)
        return None
    return dict(zip(df["item"], df["value"]))


def stock_basic(code, max_retries=3):
    """雪球个股基本信息 -> {full_name, industry, ipo_date}。"""
    kv = _xq_kv(ak.stock_individual_basic_info_xq, code, max_retries)
    if kv is None:
        return None
    ipo = None
    if kv.get("listed_date") is not None:
        ipo = datetime.fromtimestamp(kv["listed_date"] / 1000,
                                     _CST).strftime("%Y-%m-%d")
    ind = kv.get("affiliate_industry")
    return {
        "full_name": kv.get("org_name_cn"),
        "industry": ind.get("ind_name") if isinstance(ind, dict) else None,
        "ipo_date": ipo,
    }


def stock_quote(code, max_retries=3):
    """雪球个股实时 -> {pb, high_52w, low_52w, total_market_cap}。"""
    kv = _xq_kv(ak.stock_individual_spot_xq, code, max_retries)
    if kv is None:
        return None

    def num(k):
        v = kv.get(k)
        if v is None or v == "" or pd.isna(v):
            return None
        try:
            return float(v)
        except (TypeError, ValueError):  # 脏数据（如 '-'）视为无数据
            return None

    return {"pb": num("市净率"), "high_52w": num("52周最高"),
            "low_52w": num("52周最低"),
            "total_market_cap": num("资产净值/总市值")}
