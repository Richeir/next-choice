# Akshare 数据源迁移实现计划（Issue #32）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将数据源从 BaoStock 完全替换为 Akshare，移除 LLM 回填，schema 改用 6 位纯数字 code。

**Architecture:** 新增 `scripts/akshare_source.py` 数据源层（封装所有 Akshare 调用、重试限速、格式转换、日 K 重采样），重写 `scripts/fetch_data.py` 的抓取编排，保持现有 CLI 命令结构。

**Tech Stack:** Python 3.14 / akshare / pandas / sqlite3 / pytest（venv 在 `scripts/.venv`，akshare 已安装）。

**Spec:** `docs/superpowers/specs/2026-08-22-akshare-migration-design.md`

## Global Constraints

- 所有命令在仓库根目录运行；pytest 用 `scripts/.venv/bin/python -m pytest scripts/tests/...`
- `adjustflag` 语义保持项目约定：`'2'` 前复权 / `'3'` 不复权（与 `db-design.md` 一致）
- 金额单位统一为**元**；腾讯源市值 `zsz` 为"亿"（×1e8）、成交额 `turnover` 为"万"（×1e4），新浪基金规模为"万"（×1e4）
- code 存储为 6 位纯数字；新浪要 `sh600000`、雪球要 `SH600000`，转换只在 `akshare_source.py` 内做
- 东财（`*_em`）接口在当前网络不可用，禁止使用
- 串行抓取 + `--sleep`（默认 0.5）+ 指数退避重试（默认 3 次，1s/4s/16s）
- ETF K 线只有不复权（`adjustflag='3'`）；`etf_kline_daily` 的 `peTTM/pbMRQ/psTTM/pcfNcfTTM` 写 NULL
- `tradestatus` 恒写 `'1'`、`isST` 恒写 `'0'`（新数据源无此信息，文档记录该限制）
- 提交遵循 Conventional Commits（见 AGENTS.md）

---

### Task 1: schema.sql 与 transform.py 基础改造

**Files:**
- Modify: `backend/database/schema.sql`
- Modify: `scripts/transform.py`
- Test: `scripts/tests/test_transform.py`（重写）

**Interfaces:**
- Produces: `market_of(code: str) -> str`——入参 6 位纯数字，返回 `"SH"`/`"SZ"`；`to_float` 增加 NaN → None

- [ ] **Step 1: 重写测试文件**

整体替换 `scripts/tests/test_transform.py`：

```python
"""transform 工具函数单元测试。"""
import pytest

from transform import kline_table, market_of, to_float


class TestMarketOf:
    @pytest.mark.parametrize("code,market", [
        ("600000", "SH"), ("601398", "SH"), ("688981", "SH"),
        ("000001", "SZ"), ("300750", "SZ"), ("002594", "SZ"),
        ("510050", "SH"), ("560010", "SH"), ("588000", "SH"),
        ("159915", "SZ"), ("161725", "SZ"),
    ])
    def test_market_by_code_segment(self, code, market):
        assert market_of(code) == market

    def test_unknown_segment_raises(self):
        with pytest.raises(ValueError):
            market_of("900000")
        with pytest.raises(ValueError):
            market_of("sh.600000")


class TestToFloat:
    def test_empty_and_none(self):
        assert to_float("") is None
        assert to_float(None) is None

    def test_nan(self):
        assert to_float(float("nan")) is None

    def test_number(self):
        assert to_float("3.5") == 3.5
        assert to_float(2) == 2.0


class TestKlineTable:
    def test_ok(self):
        assert kline_table("stock", "daily") == "stock_kline_daily"

    def test_invalid(self):
        with pytest.raises(ValueError):
            kline_table("bond", "daily")
```

- [ ] **Step 2: 运行确认失败**

Run: `scripts/.venv/bin/python -m pytest scripts/tests/test_transform.py -v`
Expected: FAIL（`market_of("600000")` 抛 ValueError）

- [ ] **Step 3: 重写 transform.py**

```python
"""数据转换工具：类型清洗、市场推断、K 线表名。"""
import math


def to_float(value):
    """把字符串/数值转 float；None/空串/NaN 转 None。"""
    if value is None or value == "":
        return None
    f = float(value)
    if math.isnan(f):
        return None
    return f


_STOCK_SH = ("60", "68")
_STOCK_SZ = ("00", "30")
_ETF_SH = ("51", "56", "58")
_ETF_SZ = ("15", "16")


def market_of(code):
    """由 6 位纯数字 code 的号段推断市场：返回 'SH' / 'SZ'。"""
    prefix = code[:2]
    if prefix in _STOCK_SH + _ETF_SH:
        return "SH"
    if prefix in _STOCK_SZ + _ETF_SZ:
        return "SZ"
    raise ValueError(f"unknown code segment: {code!r}")


def kline_table(kind, freq):
    """返回 K 线表名，如 kline_table('stock','daily') -> 'stock_kline_daily'。"""
    if kind not in ("stock", "etf"):
        raise ValueError(f"unknown kind: {kind!r}")
    if freq not in ("daily", "weekly", "monthly"):
        raise ValueError(f"unknown frequency: {freq!r}")
    return f"{kind}_kline_{freq}"
```

- [ ] **Step 4: 运行确认通过**

Run: `scripts/.venv/bin/python -m pytest scripts/tests/test_transform.py -v`
Expected: PASS

- [ ] **Step 5: 更新 schema.sql**

对 `backend/database/schema.sql` 做四处修改：

1. `stock_info.code` 注释改为 `-- 如 600000（6 位纯数字）`；`etf_info.code` 改为 `-- 如 510050（6 位纯数字）`
2. 两表的 `market` 注释改为 `-- SH / SZ（由代码号段推断）`
3. 删除两表的 `llm_backfill_at TEXT ...` 行
4. `industry` / `category` / `manager` / `fund_scale` 注释从 "由 LLM 填充" 改为 "由 Akshare 填充"

- [ ] **Step 6: 提交**

```bash
git add backend/database/schema.sql scripts/transform.py scripts/tests/test_transform.py
git commit -m "refactor: switch schema code format and market_of to akshare style"
```

---

### Task 2: akshare_source.py 纯函数基础（代码转换 / 单位换算 / 重试）

**Files:**
- Create: `scripts/akshare_source.py`
- Test: `scripts/tests/test_akshare_source.py`

**Interfaces:**
- Produces（Task 3/4 依赖）：
  - `to_sina_code(code) -> str`（`"600000"` → `"sh600000"`）
  - `to_xq_code(code) -> str`（`"600000"` → `"SH600000"`）
  - `strip_prefix(p) -> str`（`"sh600000"` → `"600000"`）
  - `yi_to_yuan(v)`、`wan_to_yuan(v)`：None 透传
  - `fetch_with_retry(fn, *args, max_retries=3, base_delay=1.0, sleep=time.sleep, **kwargs)`：仅对 `requests.exceptions.RequestException` 重试，退避 `base_delay * 4**attempt`，耗尽后抛原异常

- [ ] **Step 1: 写失败测试**

创建 `scripts/tests/test_akshare_source.py`：

```python
"""akshare_source 数据源层单元测试（网络调用全部 mock）。"""
import pytest
import requests

import akshare_source as src


class TestCodeConversion:
    def test_to_sina(self):
        assert src.to_sina_code("600000") == "sh600000"
        assert src.to_sina_code("000001") == "sz000001"

    def test_to_xq(self):
        assert src.to_xq_code("600000") == "SH600000"
        assert src.to_xq_code("159915") == "SZ159915"

    def test_strip_prefix(self):
        assert src.strip_prefix("sh600000") == "600000"
        assert src.strip_prefix("sz000001") == "000001"


class TestUnits:
    def test_yi_to_yuan(self):
        assert src.yi_to_yuan(1.5) == 1.5e8
        assert src.yi_to_yuan(None) is None

    def test_wan_to_yuan(self):
        assert src.wan_to_yuan(2.5) == 2.5e4
        assert src.wan_to_yuan(None) is None


class TestRetry:
    def test_success_no_retry(self):
        calls = []
        def fn():
            calls.append(1)
            return "ok"
        assert src.fetch_with_retry(fn, max_retries=3, sleep=lambda s: None) == "ok"
        assert len(calls) == 1

    def test_retry_then_success(self):
        calls = []
        def fn():
            calls.append(1)
            if len(calls) < 3:
                raise requests.exceptions.ConnectionError("boom")
            return "ok"
        delays = []
        r = src.fetch_with_retry(fn, max_retries=3, base_delay=1.0,
                                 sleep=delays.append)
        assert r == "ok" and len(calls) == 3
        assert delays == [1.0, 4.0]

    def test_exhausted_raises(self):
        def fn():
            raise requests.exceptions.ConnectionError("boom")
        with pytest.raises(requests.exceptions.ConnectionError):
            src.fetch_with_retry(fn, max_retries=2, sleep=lambda s: None)

    def test_non_network_error_not_retried(self):
        calls = []
        def fn():
            calls.append(1)
            raise KeyError("data")
        with pytest.raises(KeyError):
            src.fetch_with_retry(fn, max_retries=3, sleep=lambda s: None)
        assert len(calls) == 1
```

- [ ] **Step 2: 运行确认失败**

Run: `scripts/.venv/bin/python -m pytest scripts/tests/test_akshare_source.py -v`
Expected: FAIL（ModuleNotFoundError: akshare_source）

- [ ] **Step 3: 实现**

创建 `scripts/akshare_source.py`：

```python
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
```

- [ ] **Step 4: 运行确认通过**

Run: `scripts/.venv/bin/python -m pytest scripts/tests/test_akshare_source.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add scripts/akshare_source.py scripts/tests/test_akshare_source.py
git commit -m "feat(scripts): add akshare source layer with retry and code conversion"
```

---

### Task 3: akshare_source.py K 线与重采样

**Files:**
- Modify: `scripts/akshare_source.py`
- Test: `scripts/tests/test_akshare_source.py`（追加）

**Interfaces:**
- Produces（Task 6 依赖）：
  - `KLINE_COLS = ["date","open","high","low","close","preclose","volume","amount","turn","pctChg"]`
  - `stock_kline(code, start, end, adjust="", max_retries=3) -> pd.DataFrame | None`：`adjust` 取值 `""`（不复权）/`"qfq"`/`"hfq"`；新浪 `stock_zh_a_daily`，`turnover` 列（换手率%）映射为 `turn`；失败返回 None
  - `etf_kline(code, start, end, max_retries=3) -> pd.DataFrame | None`：新浪 `fund_etf_hist_sina`（返回全量历史，本地按日期过滤），`prevclose` 列映射为 `preclose`
  - `resample_kline(df, freq) -> pd.DataFrame`：`freq` 为 `"weekly"`/`"monthly"`；date 取组内最后交易日，open 首值、close 尾值、high max、low min、volume/amount 求和、turn None、preclose 上一根 close、pctChg 由 preclose 推导

- [ ] **Step 1: 追加失败测试**

追加到 `scripts/tests/test_akshare_source.py`：

```python
import pandas as pd


def _daily_df():
    # 2024-01-02(二) ~ 2024-01-05(五)，同一交易周
    rows = [
        ("2024-01-02", 10.0, 11.0, 9.0, 10.5, 9.9, 1000, 10500, 1.0),
        ("2024-01-03", 10.5, 12.0, 10.0, 11.0, 10.5, 2000, 22000, 2.0),
        ("2024-01-04", 11.0, 11.5, 10.5, 10.8, 11.0, 1500, 16200, 1.5),
        ("2024-01-05", 10.8, 11.2, 10.2, 11.1, 10.8, 1800, 19980, 1.8),
    ]
    cols = ["date", "open", "high", "low", "close", "preclose",
            "volume", "amount", "turn"]
    return pd.DataFrame(rows, columns=cols)


class TestResample:
    def test_weekly_groups_by_week(self):
        out = src.resample_kline(_daily_df(), "weekly")
        assert len(out) == 1
        r = out.iloc[0]
        assert r["date"] == "2024-01-05"      # 组内最后交易日
        assert r["open"] == 10.0 and r["close"] == 11.1
        assert r["high"] == 12.0 and r["low"] == 9.0
        assert r["volume"] == 6300 and r["amount"] == 68680
        assert pd.isna(r["turn"])

    def test_monthly(self):
        out = src.resample_kline(_daily_df(), "monthly")
        assert len(out) == 1 and out.iloc[0]["close"] == 11.1

    def test_two_weeks_preclose_and_pct(self):
        d1 = _daily_df()
        d2 = _daily_df()
        d2["date"] = ["2024-01-08", "2024-01-09", "2024-01-10", "2024-01-11"]
        out = src.resample_kline(pd.concat([d1, d2], ignore_index=True), "weekly")
        assert len(out) == 2
        assert out.iloc[1]["preclose"] == 11.1
        assert out.iloc[1]["pctChg"] == pytest.approx(0.0)
        assert pd.isna(out.iloc[0]["preclose"])

    def test_invalid_freq(self):
        with pytest.raises(ValueError):
            src.resample_kline(_daily_df(), "daily")


class TestKlineNormalize:
    def test_stock_kline_normalizes(self, monkeypatch):
        raw = pd.DataFrame([
            ("2024-01-02", 10.0, 11.0, 9.0, 10.5, 1000, 10500, 1e10, 1.0),
            ("2024-01-03", 10.5, 12.0, 10.0, 11.0, 2000, 22000, 1e10, 2.0),
        ], columns=["date", "open", "high", "low", "close",
                    "volume", "amount", "outstanding_share", "turnover"])
        monkeypatch.setattr(src.ak, "stock_zh_a_daily", lambda **kw: raw)
        df = src.stock_kline("600000", "2024-01-01", "2024-01-31", adjust="qfq")
        assert list(df.columns) == src.KLINE_COLS
        assert pd.isna(df.iloc[0]["preclose"])
        assert df.iloc[1]["preclose"] == 10.5
        assert df.iloc[1]["pctChg"] == pytest.approx((11.0 / 10.5 - 1) * 100)
        assert df.iloc[1]["turn"] == 2.0

    def test_stock_kline_failure_returns_none(self, monkeypatch):
        def boom(**kw):
            raise requests.exceptions.ConnectionError("boom")
        monkeypatch.setattr(src.ak, "stock_zh_a_daily", boom)
        assert src.stock_kline("600000", "2024-01-01", "2024-01-31",
                               max_retries=0) is None

    def test_etf_kline_filters_dates(self, monkeypatch):
        raw = pd.DataFrame([
            ("2023-12-29", 2.99, 3.0, 3.1, 2.9, 3.0, 500, 1500, 0, 0),
            ("2024-01-02", 3.0, 3.0, 3.2, 2.95, 3.1, 600, 1860, 0, 0),
        ], columns=["date", "prevclose", "open", "high", "low", "close",
                    "volume", "amount", "postVol", "postAmt"])
        monkeypatch.setattr(src.ak, "fund_etf_hist_sina", lambda symbol: raw)
        df = src.etf_kline("510050", "2024-01-01", "2024-01-31")
        assert len(df) == 1
        assert df.iloc[0]["preclose"] == 3.0
```

- [ ] **Step 2: 运行确认失败**

Run: `scripts/.venv/bin/python -m pytest scripts/tests/test_akshare_source.py -v`
Expected: FAIL（resample_kline/stock_kline 未定义）

- [ ] **Step 3: 实现**

追加到 `scripts/akshare_source.py`：

```python
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
```

- [ ] **Step 4: 运行确认通过**

Run: `scripts/.venv/bin/python -m pytest scripts/tests/test_akshare_source.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add scripts/akshare_source.py scripts/tests/test_akshare_source.py
git commit -m "feat(scripts): add kline fetch and weekly/monthly resampling"
```

---

### Task 4: akshare_source.py 列表与个股信息

**Files:**
- Modify: `scripts/akshare_source.py`
- Test: `scripts/tests/test_akshare_source.py`（追加）

**Interfaces:**
- Produces（Task 5/7 依赖）：
  - `list_stocks(max_retries=3) -> list[dict]`：键 `code,name,pe_ttm,total_market_cap,last_close,last_pct_chg,last_amount`（元；`zsz` 亿×1e8、`turnover` 万×1e4）；失败抛异常
  - `list_etfs(max_retries=3) -> list[dict]`：键 `code,name`
  - `etf_category_map(max_retries=3) -> dict[str,str]`：code → 基金类型
  - `fund_scale_map(max_retries=3) -> dict[str,dict]`：code → `{"fund_scale": 元, "manager": str, "ipo_date": "YYYY-MM-DD"}`
  - `stock_basic(code, max_retries=3) -> dict | None`：键 `full_name,industry,ipo_date`（`affiliate_industry` 为 dict 取 `ind_name`；`listed_date` 毫秒时间戳按 UTC+8 转日期）
  - `stock_quote(code, max_retries=3) -> dict | None`：键 `pb,high_52w,low_52w,total_market_cap`（"资产净值/总市值"已是元）

- [ ] **Step 1: 追加失败测试**

追加到 `scripts/tests/test_akshare_source.py`：

```python
def _kv_df(pairs):
    return pd.DataFrame(pairs, columns=["item", "value"])


class TestListStocks:
    def test_maps_tx_columns_and_units(self, monkeypatch):
        raw = pd.DataFrame([{
            "code": "sh600519", "name": "贵州茅台", "pe_ttm": 19.5,
            "zsz": 15911.41, "zxj": 1272.83, "zdf": -1.45, "turnover": 427831,
        }])
        monkeypatch.setattr(src.ak, "stock_zh_a_spot_tx", lambda: raw)
        rows = src.list_stocks()
        assert rows[0] == {
            "code": "600519", "name": "贵州茅台", "pe_ttm": 19.5,
            "total_market_cap": pytest.approx(15911.41e8),
            "last_close": 1272.83, "last_pct_chg": -1.45,
            "last_amount": pytest.approx(427831e4),
        }


class TestListEtfs:
    def test_maps_sina_columns(self, monkeypatch):
        raw = pd.DataFrame([{"代码": "510050", "名称": "华夏上证50ETF"}])
        monkeypatch.setattr(src.ak, "fund_etf_category_sina",
                            lambda symbol: raw)
        assert src.list_etfs() == [{"code": "510050", "name": "华夏上证50ETF"}]


class TestEtfMaps:
    def test_category_map(self, monkeypatch):
        raw = pd.DataFrame([{"基金代码": "510050", "基金类型": "股票型"}])
        monkeypatch.setattr(src.ak, "fund_etf_category_ths",
                            lambda symbol: raw)
        assert src.etf_category_map() == {"510050": "股票型"}

    def test_fund_scale_map(self, monkeypatch):
        raw = pd.DataFrame([{
            "基金代码": "510300", "总募集规模": 3296860.0,
            "基金经理": "柳军", "成立日期": "2012-05-04"}])
        monkeypatch.setattr(src.ak, "fund_scale_open_sina", lambda: raw)
        m = src.fund_scale_map()
        assert m["510300"] == {"fund_scale": pytest.approx(3296860.0e4),
                               "manager": "柳军", "ipo_date": "2012-05-04"}


class TestStockInfoXq:
    def test_basic(self, monkeypatch):
        raw = _kv_df([
            ("org_name_cn", "上海浦东发展银行股份有限公司"),
            ("listed_date", 942163200000),  # 1999-11-10 UTC+8
            ("affiliate_industry", {"ind_code": "BK0055", "ind_name": "银行"}),
        ])
        monkeypatch.setattr(src.ak, "stock_individual_basic_info_xq",
                            lambda symbol: raw)
        info = src.stock_basic("600000")
        assert info == {"full_name": "上海浦东发展银行股份有限公司",
                        "industry": "银行", "ipo_date": "1999-11-10"}

    def test_quote(self, monkeypatch):
        raw = _kv_df([("市净率", 0.5), ("52周最高", 13.6), ("52周最低", 8.1),
                      ("资产净值/总市值", 3.01e11)])
        monkeypatch.setattr(src.ak, "stock_individual_spot_xq",
                            lambda symbol: raw)
        assert src.stock_quote("600000") == {
            "pb": 0.5, "high_52w": 13.6, "low_52w": 8.1,
            "total_market_cap": 3.01e11}

    def test_basic_failure_returns_none(self, monkeypatch):
        def boom(symbol):
            raise requests.exceptions.ConnectionError("boom")
        monkeypatch.setattr(src.ak, "stock_individual_basic_info_xq", boom)
        assert src.stock_basic("600000", max_retries=0) is None
```

- [ ] **Step 2: 运行确认失败**

Run: `scripts/.venv/bin/python -m pytest scripts/tests/test_akshare_source.py -v`
Expected: FAIL（list_stocks 等未定义）

- [ ] **Step 3: 实现**

追加到 `scripts/akshare_source.py`：

```python
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
    """新浪 ETF 列表。"""
    df = fetch_with_retry(ak.fund_etf_category_sina, symbol="ETF基金",
                          max_retries=max_retries)
    return [{"code": str(r["代码"]), "name": r["名称"]}
            for _, r in df.iterrows()]


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


def _xq_kv(fetch_fn, code, max_retries):
    """雪球 item/value 两列 DataFrame -> dict。失败返回 None。"""
    try:
        df = fetch_with_retry(fetch_fn, symbol=to_xq_code(code),
                              max_retries=max_retries)
    except Exception as e:
        log.warning("xq fetch %s failed: %s", code, e)
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
        return float(v)

    return {"pb": num("市净率"), "high_52w": num("52周最高"),
            "low_52w": num("52周最低"),
            "total_market_cap": num("资产净值/总市值")}
```

- [ ] **Step 4: 运行确认通过**

Run: `scripts/.venv/bin/python -m pytest scripts/tests/test_akshare_source.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add scripts/akshare_source.py scripts/tests/test_akshare_source.py
git commit -m "feat(scripts): add akshare list and per-stock info fetchers"
```

---

### Task 5: fetch_data.py 列表命令重写

**Files:**
- Modify: `scripts/fetch_data.py`（整体重写；本任务完成列表命令 + 解析器，K 线/info 命令在 Task 6/7 补充）
- Test: `scripts/tests/test_fetch_stock_list.py`（重写）、`scripts/tests/test_fetch_etf_list.py`（重写）

**Interfaces:**
- Consumes: `transform.market_of`（Task 1）；`src.list_stocks/list_etfs/etf_category_map/fund_scale_map`（Task 4）
- Produces（Task 6/7 依赖）：`update_stock_list(conn) -> (n_ok, n_fail)`、`update_etf_list(conn) -> (n_ok, n_fail)`、`build_parser()`、`resolve_date_range(start, end, years=5)`

- [ ] **Step 1: 重写 fetch_data.py**

删除原文件全部内容，写入：

```python
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
```

- [ ] **Step 2: 重写列表测试**

整体替换 `scripts/tests/test_fetch_stock_list.py`：

```python
"""fetch_data.update_stock_list 单元测试：mock akshare_source。"""
import pytest

import db
import fetch_data
from conftest import SCHEMA


@pytest.fixture()
def conn(tmp_path):
    return db.init_db(str(tmp_path / "test.db"), SCHEMA)


def _stocks():
    return [{"code": "600000", "name": "浦发银行", "pe_ttm": 4.2,
             "total_market_cap": 3.01e11, "last_close": 9.05,
             "last_pct_chg": -0.66, "last_amount": 4.28e9},
            {"code": "000001", "name": "平安银行", "pe_ttm": 5.1,
             "total_market_cap": 2.0e11, "last_close": 10.3,
             "last_pct_chg": 0.5, "last_amount": 1.0e9}]


class TestUpdateStockList:
    def test_writes_all_fields(self, conn, monkeypatch):
        monkeypatch.setattr(fetch_data.src, "list_stocks",
                            lambda **kw: _stocks())
        n_ok, n_fail = fetch_data.update_stock_list(conn)
        assert (n_ok, n_fail) == (2, 0)
        row = conn.execute(
            "SELECT * FROM stock_info WHERE code='600000'").fetchone()
        assert row["code_name"] == "浦发银行"
        assert row["market"] == "SH"
        assert row["type"] == "1" and row["status"] == "1"
        assert row["pe_ttm"] == 4.2
        assert row["total_market_cap"] == 3.01e11
        assert row["last_amount"] == 4.28e9
        assert row["last_close"] == 9.05
        assert row["last_pct_chg"] == -0.66
        assert row["last_trade_date"] is not None

    def test_market_sz(self, conn, monkeypatch):
        monkeypatch.setattr(fetch_data.src, "list_stocks",
                            lambda **kw: _stocks())
        fetch_data.update_stock_list(conn)
        row = conn.execute(
            "SELECT market FROM stock_info WHERE code='000001'").fetchone()
        assert row["market"] == "SZ"
```

整体替换 `scripts/tests/test_fetch_etf_list.py`：

```python
"""fetch_data.update_etf_list 单元测试：mock akshare_source。"""
import pytest

import db
import fetch_data
from conftest import SCHEMA


@pytest.fixture()
def conn(tmp_path):
    return db.init_db(str(tmp_path / "test.db"), SCHEMA)


class TestUpdateEtfList:
    def test_joins_three_sources(self, conn, monkeypatch):
        monkeypatch.setattr(fetch_data.src, "list_etfs", lambda **kw:
                            [{"code": "510050", "name": "上证50ETF"},
                             {"code": "159915", "name": "创业板ETF"}])
        monkeypatch.setattr(fetch_data.src, "etf_category_map",
                            lambda **kw: {"510050": "股票型"})
        monkeypatch.setattr(fetch_data.src, "fund_scale_map", lambda **kw:
                            {"510050": {"fund_scale": 5.0e10,
                                        "manager": "柳军",
                                        "ipo_date": "2004-12-30"}})
        n_ok, n_fail = fetch_data.update_etf_list(conn)
        assert (n_ok, n_fail) == (2, 0)
        row = conn.execute(
            "SELECT * FROM etf_info WHERE code='510050'").fetchone()
        assert row["market"] == "SH" and row["type"] == "5"
        assert row["category"] == "股票型"
        assert row["manager"] == "柳军"
        assert row["fund_scale"] == 5.0e10
        assert row["ipoDate"] == "2004-12-30"
        row2 = conn.execute(
            "SELECT category, manager, fund_scale FROM etf_info"
            " WHERE code='159915'").fetchone()
        assert row2["category"] is None and row2["manager"] is None
        assert row2["fund_scale"] is None
```

- [ ] **Step 3: 运行确认通过**

Run: `scripts/.venv/bin/python -m pytest scripts/tests/test_fetch_stock_list.py scripts/tests/test_fetch_etf_list.py -v`
Expected: PASS

- [ ] **Step 4: 提交**

```bash
git add scripts/fetch_data.py scripts/tests/test_fetch_stock_list.py scripts/tests/test_fetch_etf_list.py
git commit -m "feat(scripts): rewrite list commands on akshare sources"
```

---

### Task 6: fetch_data.py K 线命令与增量逻辑

**Files:**
- Modify: `scripts/fetch_data.py`
- Test: `scripts/tests/test_fetch_stock_kline.py`（重写）、`scripts/tests/test_fetch_etf_kline.py`（重写）、`scripts/tests/test_fetch_incremental.py`（重写）

**Interfaces:**
- Consumes: `src.stock_kline/etf_kline/resample_kline`（Task 3）；`db.insert_kline(conn, kind, freq, adjustflag, rows)`、`db._TABLE_COLS`、`db.fetched_today/mark_fetched/kline_max_date`（已存在，不改签名）
- Produces（Task 7 main 依赖）：
  - `_kline_rows(kind, freq, df, code, adjustflag) -> list[list]`
  - `_due_freqs(freqs, today, last_dates) -> list`（与旧版逻辑一致）
  - `fetch_stock_kline(conn, freqs, adjusts, start, end, force=False, today=None, incremental=False, sleep_s=0.5, max_retries=3) -> (n_ok, n_fail)`
  - `fetch_etf_kline(...)` 同签名

- [ ] **Step 1: 实现 K 线抓取逻辑**

在 `fetch_data.py` 中 `build_parser` 之前插入（`main` 的 else 分支替换在 Task 7 完成）：

```python
VALID_ADJUST = ("2", "3")
_ADJUST_SINA = {"3": "", "2": "qfq"}
# 增量重采样的周期边界余量（周 10 天 / 月 40 天，日 K 重拉 1 天覆盖修正）
_INC_PAD_DAYS = {"daily": 1, "weekly": 10, "monthly": 40}


def _due_freqs(freqs, today, last_dates):
    """增量模式频率门控（与旧版一致）：
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
    db._TABLE_COLS；weekly/monthly 表无 preclose 列，vals 多余键自动忽略）。"""
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
                if incremental:
                    base = last_dates.get(freq) or start
                    pad = _INC_PAD_DAYS[freq]
                    fstart = (date.fromisoformat(base)
                              - timedelta(days=pad)).isoformat()
                else:
                    fstart = start
                for adj in adjusts:
                    _fetch_one_kline(conn, kind, code, freq, adj, fstart, end,
                                     max_retries)
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
```

- [ ] **Step 2: 重写 K 线测试**

整体替换 `scripts/tests/test_fetch_stock_kline.py`：

```python
"""fetch_data 股票 K 线命令单元测试：mock akshare_source。"""
import pandas as pd
import pytest

import db
import fetch_data
from conftest import SCHEMA

COLS = fetch_data.src.KLINE_COLS


def _df(rows):
    return pd.DataFrame(rows, columns=COLS)


@pytest.fixture()
def conn(tmp_path):
    c = db.init_db(str(tmp_path / "test.db"), SCHEMA)
    c.execute("INSERT INTO stock_info (code, code_name, market, type, status)"
              " VALUES ('600000','浦发银行','SH','1','1')")
    c.commit()
    return c


def _two_days():
    return _df([("2024-01-02", 10, 11, 9, 10.5, 9.9, 1000, 1e4, 1.0, 6.06),
                ("2024-01-03", 10.5, 12, 10, 11.0, 10.5, 2000, 2e4, 2.0, 4.76)])


class TestFetchStockKline:
    def test_daily_two_adjusts(self, conn, monkeypatch):
        seen = []
        def fake(code, start, end, adjust="", max_retries=3):
            seen.append(adjust)
            return _two_days()
        monkeypatch.setattr(fetch_data.src, "stock_kline", fake)
        n_ok, n_fail = fetch_data.fetch_stock_kline(
            conn, ["daily"], ["2", "3"], "2024-01-01", "2024-01-31",
            sleep_s=0)
        assert (n_ok, n_fail) == (1, 0)
        assert sorted(seen) == ["", "qfq"]
        rows = conn.execute("SELECT adjustflag, count(*) n FROM"
                            " stock_kline_daily GROUP BY adjustflag").fetchall()
        assert {r["adjustflag"]: r["n"] for r in rows} == {"2": 2, "3": 2}

    def test_daily_row_fields(self, conn, monkeypatch):
        monkeypatch.setattr(fetch_data.src, "stock_kline",
                            lambda *a, **kw: _two_days())
        fetch_data.fetch_stock_kline(conn, ["daily"], ["3"],
                                     "2024-01-01", "2024-01-31", sleep_s=0)
        row = conn.execute("SELECT * FROM stock_kline_daily"
                           " WHERE date='2024-01-03'").fetchone()
        assert row["preclose"] == 10.5
        assert row["tradestatus"] == "1" and row["isST"] == "0"
        assert row["turn"] == 2.0

    def test_weekly_resampled(self, conn, monkeypatch):
        monkeypatch.setattr(fetch_data.src, "stock_kline",
                            lambda *a, **kw: _two_days())
        fetch_data.fetch_stock_kline(conn, ["weekly"], ["3"],
                                     "2024-01-01", "2024-01-31", sleep_s=0)
        row = conn.execute("SELECT * FROM stock_kline_weekly").fetchone()
        assert row["date"] == "2024-01-03"
        assert row["open"] == 10 and row["close"] == 11.0
        assert row["volume"] == 3000

    def test_source_failure_counts_fail(self, conn, monkeypatch):
        monkeypatch.setattr(fetch_data.src, "stock_kline",
                            lambda *a, **kw: None)
        n_ok, n_fail = fetch_data.fetch_stock_kline(
            conn, ["daily"], ["3"], "2024-01-01", "2024-01-31", sleep_s=0)
        assert (n_ok, n_fail) == (0, 1)
```

整体替换 `scripts/tests/test_fetch_etf_kline.py`：

```python
"""fetch_data ETF K 线命令单元测试：mock akshare_source。"""
import pandas as pd
import pytest

import db
import fetch_data
from conftest import SCHEMA


def _df(rows):
    return pd.DataFrame(rows, columns=fetch_data.src.KLINE_COLS)


@pytest.fixture()
def conn(tmp_path):
    c = db.init_db(str(tmp_path / "test.db"), SCHEMA)
    c.execute("INSERT INTO etf_info (code, code_name, market, type, status)"
              " VALUES ('510050','上证50ETF','SH','5','1')")
    c.commit()
    return c


class TestFetchEtfKline:
    def test_adjust_forced_to_3(self, conn, monkeypatch):
        monkeypatch.setattr(fetch_data.src, "etf_kline", lambda *a, **kw: _df(
            [("2024-01-02", 3.0, 3.1, 2.9, 3.05, 2.99, 500, 1500, None, 2.0)]))
        n_ok, n_fail = fetch_data.fetch_etf_kline(
            conn, ["daily"], ["2", "3"], "2024-01-01", "2024-01-31", sleep_s=0)
        assert (n_ok, n_fail) == (1, 0)
        rows = conn.execute("SELECT adjustflag FROM etf_kline_daily").fetchall()
        assert [r["adjustflag"] for r in rows] == ["3"]

    def test_valuation_columns_null(self, conn, monkeypatch):
        monkeypatch.setattr(fetch_data.src, "etf_kline", lambda *a, **kw: _df(
            [("2024-01-02", 3.0, 3.1, 2.9, 3.05, 2.99, 500, 1500, None, 2.0)]))
        fetch_data.fetch_etf_kline(conn, ["daily"], ["3"],
                                   "2024-01-01", "2024-01-31", sleep_s=0)
        row = conn.execute("SELECT * FROM etf_kline_daily").fetchone()
        assert row["peTTM"] is None and row["pbMRQ"] is None
        assert row["psTTM"] is None and row["pcfNcfTTM"] is None
        assert row["preclose"] == 2.99
```

整体替换 `scripts/tests/test_fetch_incremental.py`：

```python
"""fetch_data 增量逻辑单元测试：频率门控 _due_freqs + 增量起始日回退。"""
from datetime import date

import pandas as pd
import pytest

import db
import fetch_data
from conftest import SCHEMA


class TestDueFreqs:
    def test_new_security_all_freqs(self):
        assert fetch_data._due_freqs(
            ["daily", "weekly", "monthly"], date(2024, 1, 3),
            {"daily": None, "weekly": None, "monthly": None}
        ) == ["daily", "weekly", "monthly"]

    def test_daily_only_weekday(self):
        assert fetch_data._due_freqs(["daily"], date(2024, 1, 6),  # 周六
                                     {"daily": "2024-01-05"}) == []
        assert fetch_data._due_freqs(["daily"], date(2024, 1, 8),  # 周一
                                     {"daily": "2024-01-05"}) == ["daily"]

    def test_weekly_weekend_gate(self):
        # 周六，最后周 K 距今 3 天 -> 到期
        assert fetch_data._due_freqs(["weekly"], date(2024, 1, 6),
                                     {"weekly": "2024-01-03"}) == ["weekly"]
        # 周六，最后周 K 就是昨天 -> 不门控（已抓过本周）
        assert fetch_data._due_freqs(["weekly"], date(2024, 1, 6),
                                     {"weekly": "2024-01-05"}) == []
        # 工作日但距今超 7 天（补漏）
        assert fetch_data._due_freqs(["weekly"], date(2024, 1, 15),
                                     {"weekly": "2024-01-03"}) == ["weekly"]

    def test_monthly_gate(self):
        assert fetch_data._due_freqs(["monthly"], date(2024, 1, 2),
                                     {"monthly": "2023-12-29"}) == ["monthly"]
        assert fetch_data._due_freqs(["monthly"], date(2024, 1, 15),
                                     {"monthly": "2023-12-29"}) == []
        assert fetch_data._due_freqs(["monthly"], date(2024, 2, 15),
                                     {"monthly": "2023-12-29"}) == ["monthly"]


class TestIncrementalStart:
    def test_starts_from_last_date_minus_pad(self, tmp_path, monkeypatch):
        conn = db.init_db(str(tmp_path / "t.db"), SCHEMA)
        conn.execute("INSERT INTO stock_info (code, code_name, market, type,"
                     " status) VALUES ('600000','浦发银行','SH','1','1')")
        # 注意：增量起始日取自该频率的 K 线表（这里必须插周 K 表）
        conn.execute("INSERT INTO stock_kline_weekly (date, code, close,"
                     " adjustflag) VALUES ('2024-01-05','600000',10.5,'3')")
        conn.commit()
        seen = {}
        def fake(code, start, end, adjust="", max_retries=3):
            seen["start"] = start
            return pd.DataFrame(columns=fetch_data.src.KLINE_COLS)
        monkeypatch.setattr(fetch_data.src, "stock_kline", fake)
        fetch_data.fetch_stock_kline(conn, ["weekly"], ["3"], "2020-01-01",
                                     "2024-01-31", incremental=True,
                                     today="2024-01-13", sleep_s=0)  # 周六
        # 最后周 K 2024-01-05，回退 10 天
        assert seen["start"] == "2023-12-26"
```

- [ ] **Step 3: 运行确认通过**

Run: `scripts/.venv/bin/python -m pytest scripts/tests/test_fetch_stock_kline.py scripts/tests/test_fetch_etf_kline.py scripts/tests/test_fetch_incremental.py -v`
Expected: PASS

- [ ] **Step 4: 提交**

```bash
git add scripts/fetch_data.py scripts/tests/test_fetch_stock_kline.py scripts/tests/test_fetch_etf_kline.py scripts/tests/test_fetch_incremental.py
git commit -m "feat(scripts): rewrite kline commands with resampling and incremental gate"
```

---

### Task 7: fetch_data.py 个股补齐命令、--codes 路径与 main 接线

**Files:**
- Modify: `scripts/fetch_data.py`
- Test: `scripts/tests/test_fetch_stock_info.py`（新建）、`scripts/tests/test_fetch.py`（重写）

**Interfaces:**
- Consumes: `src.stock_basic/stock_quote`（Task 4）；Task 5/6 的全部函数
- Produces: `fetch_stock_info(conn, limit=None, sleep_s=0.5, max_retries=3) -> (n_ok, n_fail)`；`run_fetch(conn, codes, freqs, adjusts, start, end, max_retries)`；完整 `main`

- [ ] **Step 1: 写失败测试**

创建 `scripts/tests/test_fetch_stock_info.py`：

```python
"""fetch_data.fetch_stock_info 单元测试：雪球逐只补齐，跳过已抓过的。"""
import pytest

import db
import fetch_data
from conftest import SCHEMA


@pytest.fixture()
def conn(tmp_path):
    c = db.init_db(str(tmp_path / "test.db"), SCHEMA)
    c.execute("INSERT INTO stock_info (code, code_name, market, type, status)"
              " VALUES ('600000','浦发银行','SH','1','1')")
    c.execute("INSERT INTO stock_info (code, code_name, market, type, status,"
              " full_name) VALUES ('000001','平安银行','SZ','1','1','已抓过')")
    c.commit()
    return c


class TestFetchStockInfo:
    def test_only_fills_missing(self, conn, monkeypatch):
        calls = []
        monkeypatch.setattr(fetch_data.src, "stock_basic",
                            lambda code, **kw: calls.append(code) or {
                                "full_name": "上海浦东发展银行股份有限公司",
                                "industry": "银行", "ipo_date": "1999-11-10"})
        monkeypatch.setattr(fetch_data.src, "stock_quote",
                            lambda code, **kw: {"pb": 0.5, "high_52w": 13.6,
                                                "low_52w": 8.1,
                                                "total_market_cap": 3.01e11})
        n_ok, n_fail = fetch_data.fetch_stock_info(conn, sleep_s=0)
        assert (n_ok, n_fail) == (1, 0)
        assert calls == ["600000"]  # 000001 已有 full_name，跳过
        row = conn.execute("SELECT * FROM stock_info WHERE code='600000'"
                           ).fetchone()
        assert row["full_name"] == "上海浦东发展银行股份有限公司"
        assert row["industry"] == "银行"
        assert row["ipoDate"] == "1999-11-10"
        assert row["pb"] == 0.5 and row["high_52w"] == 13.6
        assert row["low_52w"] == 8.1
        assert row["total_market_cap"] == 3.01e11

    def test_limit(self, conn, monkeypatch):
        monkeypatch.setattr(fetch_data.src, "stock_basic",
                            lambda code, **kw: None)
        monkeypatch.setattr(fetch_data.src, "stock_quote",
                            lambda code, **kw: None)
        n_ok, n_fail = fetch_data.fetch_stock_info(conn, limit=0, sleep_s=0)
        assert (n_ok, n_fail) == (0, 0)

    def test_source_failure_counts_fail(self, conn, monkeypatch):
        monkeypatch.setattr(fetch_data.src, "stock_basic",
                            lambda code, **kw: None)
        monkeypatch.setattr(fetch_data.src, "stock_quote",
                            lambda code, **kw: None)
        n_ok, n_fail = fetch_data.fetch_stock_info(conn, sleep_s=0)
        assert (n_ok, n_fail) == (0, 1)
```

整体替换 `scripts/tests/test_fetch.py`（--codes 路径 + CLI 解析）：

```python
"""fetch_data run_fetch（--codes 路径）与 CLI 解析测试。"""
import pandas as pd
import pytest

import db
import fetch_data
from conftest import SCHEMA


@pytest.fixture()
def conn(tmp_path):
    return db.init_db(str(tmp_path / "test.db"), SCHEMA)


class TestRunFetch:
    def test_stock_codes(self, conn, monkeypatch):
        monkeypatch.setattr(fetch_data.src, "stock_basic",
                            lambda code, **kw: {"full_name": "全称",
                                                "industry": "银行",
                                                "ipo_date": "1999-11-10"})
        monkeypatch.setattr(fetch_data.src, "stock_kline",
                            lambda *a, **kw: pd.DataFrame(
                                [("2024-01-02", 10, 11, 9, 10.5, 9.9,
                                  1000, 1e4, 1.0, 6.0)],
                                columns=fetch_data.src.KLINE_COLS))
        fetch_data.run_fetch(conn, ["600000"], ["daily"], ["3"],
                             "2024-01-01", "2024-01-31")
        info = conn.execute("SELECT * FROM stock_info WHERE code='600000'"
                            ).fetchone()
        assert info["code_name"] == "全称"  # 无列表源时用 full_name
        assert info["industry"] == "银行"
        assert conn.execute("SELECT count(*) c FROM stock_kline_daily"
                            ).fetchone()["c"] == 1

    def test_etf_codes(self, conn, monkeypatch):
        monkeypatch.setattr(fetch_data.src, "etf_kline",
                            lambda *a, **kw: pd.DataFrame(
                                [("2024-01-02", 3.0, 3.1, 2.9, 3.05, 2.99,
                                  500, 1500, None, 2.0)],
                                columns=fetch_data.src.KLINE_COLS))
        fetch_data.run_fetch(conn, ["510050"], ["daily"], ["3"],
                             "2024-01-01", "2024-01-31")
        assert conn.execute("SELECT count(*) c FROM etf_kline_daily"
                            ).fetchone()["c"] == 1


class TestParser:
    def test_mutually_exclusive(self):
        with pytest.raises(SystemExit):
            fetch_data.build_parser().parse_args(
                ["--update-stock-list", "--update-etf-list"])

    def test_requires_command(self):
        with pytest.raises(SystemExit):
            fetch_data.build_parser().parse_args([])
```

- [ ] **Step 2: 运行确认失败**

Run: `scripts/.venv/bin/python -m pytest scripts/tests/test_fetch_stock_info.py scripts/tests/test_fetch.py -v`
Expected: FAIL（fetch_stock_info/run_fetch 未定义）

- [ ] **Step 3: 实现**

在 `fetch_data.py` 中 `build_parser` 之前插入：

```python
_STOCK_INFO_COLS = ("full_name", "industry", "ipoDate", "pb",
                    "high_52w", "low_52w", "total_market_cap")


def fetch_stock_info(conn, limit=None, sleep_s=0.5, max_retries=3):
    """雪球逐只补齐个股字段，仅处理 full_name 为空的在市股票；
    basic 与 quote 任一成功即写库（部分成功也入库），两者皆失败记 fail。"""
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
        basic = src.stock_basic(code, max_retries=max_retries)
        quote = src.stock_quote(code, max_retries=max_retries)
        if basic is None and quote is None:
            log.warning("stock_info %s: both xq calls failed", code)
            n_fail += 1
            continue
        basic = basic or {}
        quote = quote or {}
        sets, vals = [], []
        mapping = {"full_name": basic.get("full_name"),
                   "industry": basic.get("industry"),
                   "ipoDate": basic.get("ipo_date"),
                   "pb": quote.get("pb"), "high_52w": quote.get("high_52w"),
                   "low_52w": quote.get("low_52w"),
                   "total_market_cap": quote.get("total_market_cap")}
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
        if idx % 50 == 0 or idx == total:
            print(f"[stock-info] {idx}/{total} ok={n_ok} fail={n_fail}",
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
    prefix = code[:2]
    if prefix in ("51", "56", "58", "15", "16"):
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
        print(f"[codes] {code} done ({kind})", flush=True)
```

并把 `main` 的 `else: raise SystemExit(...)` 替换为完整分发：

```python
        elif args.fetch_stock_info:
            n_ok, n_fail = fetch_stock_info(conn, limit=args.limit,
                                            sleep_s=args.sleep,
                                            max_retries=args.max_retries)
            print(f"done. db={args.db} stock_info ok={n_ok} fail={n_fail}")
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
```

同时加校验（`build_parser` 返回前或 `_DataParser` 子类）：`--incremental` 只能与 `--fetch-stock-kline`/`--fetch-etf-kline` 同用，否则 `parser.error(...)`。

- [ ] **Step 4: 运行确认通过**

Run: `scripts/.venv/bin/python -m pytest scripts/tests/test_fetch_stock_info.py scripts/tests/test_fetch.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add scripts/fetch_data.py scripts/tests/test_fetch_stock_info.py scripts/tests/test_fetch.py
git commit -m "feat(scripts): add stock-info enrichment and codes path"
```

---

### Task 8: 清理（删除 LLM 回填 / db backfill / baostock 依赖）

**Files:**
- Delete: `scripts/llm_backfill.py`、`scripts/tests/test_llm_backfill.py`
- Modify: `scripts/db.py`（删除 `backfill_stock_info`/`backfill_etf_info`）
- Modify: `scripts/tests/test_db.py`（删除对应测试用例）
- Modify: `scripts/tests/test_e2e.py`（更新为 akshare 冒烟或删除过时的 baostock e2e）
- Modify: `scripts/tests/conftest.py`（markers 说明文字更新）
- Modify: `scripts/requirements.txt`

- [ ] **Step 1: 删除文件与 backfill 函数**

```bash
git rm scripts/llm_backfill.py scripts/tests/test_llm_backfill.py
```

从 `scripts/db.py` 删除 `backfill_stock_info` 与 `backfill_etf_info` 两个函数（及文件头注释中"行情回填"字样，改为"建库、幂等写入 K 线"）。从 `scripts/tests/test_db.py` 删除引用这两个函数的测试用例（若有其他用例依赖先跑一遍确认）。

- [ ] **Step 2: 更新 requirements.txt 与 conftest**

`scripts/requirements.txt` 整体替换为：

```
akshare==1.18.94
```

（若执行时 venv 中版本不同，以 `scripts/.venv/bin/python -m pip show akshare`
的 Version 输出为准。）

`scripts/tests/conftest.py` 中 markers 行改为：

```python
    config.addinivalue_line("markers", "e2e: real-network Akshare end-to-end tests")
```

`scripts/tests/test_e2e.py`：把 baostock 相关用例替换为等价的 akshare 冒烟（`@pytest.mark.e2e` 标记，默认跳过需 `-m e2e` 显式运行）：

```python
"""真实网络端到端冒烟（默认跳过：-m e2e 显式运行）。"""
import pytest

import akshare_source as src


@pytest.mark.e2e
def test_stock_kline_real():
    df = src.stock_kline("600000", "2024-01-02", "2024-01-05")
    assert df is not None and len(df) > 0


@pytest.mark.e2e
def test_etf_kline_real():
    df = src.etf_kline("510050", "2024-01-02", "2024-01-05")
    assert df is not None and len(df) > 0
```

- [ ] **Step 3: 运行全量脚本测试**

Run: `scripts/.venv/bin/python -m pytest scripts/tests/ -v`
Expected: 全部 PASS（无 baostock/llm_backfill 残留；用 `rg -n "baostock|llm_backfill|bs\." scripts/ --glob '!*.pyc'` 确认无引用）

- [ ] **Step 4: 提交**

```bash
git add -A scripts/
git commit -m "chore(scripts): remove baostock and llm backfill leftovers"
```

---

### Task 9: 文档更新（doc/ 与 scripts/README.md）

**Files:**
- Delete: `doc/baostock-api.md`
- Create: `doc/akshare-api.md`
- Modify: `doc/db-design.md`、`doc/architecture.md`、`doc/llm-analysis.md`、`doc/tech-stack.md`、`doc/README.md`、`scripts/README.md`

- [ ] **Step 1: 新建 doc/akshare-api.md**

内容包含（各接口附实测日期与已知限制）：

| 用途 | 接口 | 源 | 备注 |
|------|------|----|------|
| A 股列表 + 行情 | `stock_zh_a_spot_tx` | 腾讯 | `zsz` 亿、`turnover` 万，入库换算为元 |
| 股票日 K | `stock_zh_a_daily` | 新浪 | `adjust`: `""`/`qfq`/`hfq` |
| 股票周/月 K | 日 K 本地重采样 | — | 无直抓源 |
| 个股信息 | `stock_individual_basic_info_xq` | 雪球 | 全称/行业/上市日期，逐只 |
| 个股实时 | `stock_individual_spot_xq` | 雪球 | PB/52 周/市值，逐只 |
| ETF 列表 | `fund_etf_category_sina` | 新浪 | |
| ETF 日 K | `fund_etf_hist_sina` | 新浪 | 仅不复权，返回全量历史 |
| ETF 类别 | `fund_etf_category_ths` | 同花顺 | |
| ETF 规模/管理人 | `fund_scale_open_sina` | 新浪 | 规模"万"换算为元 |

并写明限制：东财系接口在当前网络不可用；`tradestatus`/`isST` 为常量；
`etf_kline_daily` 估值列恒为 NULL。

- [ ] **Step 2: 更新其余文档**

- `doc/db-design.md`：code 格式示例改 6 位纯数字；`market` 推断改号段；
  删除 `llm_backfill_at`；"脚本可回填"段落改为"由列表刷新写入（腾讯源）"；
  注明周/月 K 为本地重采样、ETF 仅不复权
- `doc/architecture.md`：数据流图/文字中 BaoStock → Akshare；删除
  LLM 回填环节；抓取计划表更新（每交易日列表+daily 增量；
  `--fetch-stock-info` 每周或手动）
- `doc/llm-analysis.md`：删除"LLM 回填基础信息"相关章节，保留分析打分
- `doc/tech-stack.md`：依赖表 baostock → akshare
- `doc/README.md`：文档索引中 `baostock-api.md` → `akshare-api.md`
- `scripts/README.md`：用法示例全部替换为新 CLI（含 `--fetch-stock-info`、
  `--sleep`、`--max-retries`）

- [ ] **Step 3: 提交**

```bash
git add doc/ scripts/README.md
git commit -m "docs: update docs for akshare data source migration"
```

---

### Task 10: 后端测试适配与端到端验证

**Files:**
- Modify: `backend/src/**/*.spec.ts`（仅测试 fixture 中 `sh.600000` 形式的示例代码）

- [ ] **Step 1: 检查后端源码**

Run: `rg -n "sh\.|sz\." backend/src --glob '!*.spec.ts'`
Expected: 无输出（源码不依赖 code 格式；若有输出则一并修改）。

- [ ] **Step 2: 更新 spec fixture**

把 `backend/src` 下 `.spec.ts` 中 `sh.600000`/`sz.000001` 等示例替换为
`600000`/`000001`（逐文件检查语义，保持断言逻辑不变）。

- [ ] **Step 3: 运行后端测试**

Run: `cd backend && npm test`（或项目配置的等价命令；先查 `backend/package.json` scripts）
Expected: 全部 PASS

- [ ] **Step 4: 手动端到端冒烟（真实网络）**

```bash
rm -f data/market.db
scripts/.venv/bin/python scripts/fetch_data.py --db data/market.db --update-stock-list
scripts/.venv/bin/python scripts/fetch_data.py --db data/market.db --update-etf-list
scripts/.venv/bin/python scripts/fetch_data.py --db data/market.db --fetch-stock-info --limit 10
scripts/.venv/bin/python scripts/fetch_data.py --db data/market.db --codes 600000,510050 --freq daily,weekly,monthly --start 2024-01-01
```

检查点（用 `sqlite3 data/market.db`）：
- `SELECT count(*) FROM stock_info;` ≈ 5500；`SELECT industry, full_name, pb FROM stock_info WHERE code='600000';` 非空
- `SELECT count(*) FROM etf_info;` ≈ 1600；`SELECT category, manager, fund_scale FROM etf_info WHERE code='510050';` 非空
- `SELECT freq.* FROM stock_kline_weekly WHERE code='600000' LIMIT 5;` 有数据
- `SELECT count(*) FROM etf_kline_daily WHERE code='510050';` 有数据
- `--incremental` 冒烟：`scripts/.venv/bin/python scripts/fetch_data.py --db data/market.db --codes 600000 --freq daily --incremental`（--codes 不支持增量，用 `--fetch-stock-kline --incremental` 跑一次确认门控日志正常）

- [ ] **Step 5: 提交并关联 issue**

```bash
git add -A
git commit -m "test(backend): update code fixtures for new akshare format" --allow-empty
# 若冒烟中发现修复，按类型分别提交
```

最后推送分支，更新 issue #32 状态（`gh issue comment 32 --body "..."` 附上迁移说明）。
