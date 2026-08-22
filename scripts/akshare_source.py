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
