# BaoStock K 线数据存储设计（SQLite）

本文件描述将 BaoStock 的股票 / ETF 日、周、月 K 线数据落库为 SQLite 的数据库设计。

## 1. 设计目标与原则

- **产品分表**：股票与 ETF **不混在同一张表**，各自独立。
- **频率分表**：日 / 周 / 月 K 各建一张表，避免混合存储造成字段与粒度混乱。
- **复权策略**：每张 K 线表同时保存 **前复权（`adjustflag='2'`）** 与 **不复权原始价（`'3'`）** 两档。
  - 前复权：符合画图 / 趋势分析需求。
  - 不复权：原始成交价"永久真实"，当某股发生新的分红送股、前复权历史价漂移时，可结合复权因子表重算最新前复权，不必整段重拉。
- **幂等写入**：以 `UNIQUE(code, date, adjustflag)` 为主键约束，重复抓取用 `INSERT OR REPLACE` / `INSERT OR IGNORE` 去重。
- **约定**：
  - `code` 带交易所前缀原文存储（如 `sh.600000`、`sh.510010`）。
  - 数值列从 BaoStock 返回的 `str` 转换为 `REAL` 入库。
  - 日期用 `TEXT` 存储，格式 `YYYY-MM-DD`（字典序即时间序）。

## 2. 数据范围与频率说明

| 频率 | 股票范围 | ETF 范围 | 字段集 |
|------|----------|----------|--------|
| 日 K | 1990-12-19 至今 | 2026-01-05 至今 | 完整字段（含 `preclose/tradestatus/isST`） |
| 周 K | 1990-12-19 至今 | 2026-01-05 至今 | 精简字段 |
| 月 K | 1990-12-19 至今 | 2026-01-05 至今 | 精简字段 |

## 3. 表清单

共 **11 张表**，按用途分四类：**基础信息（2 张）**、**K 线数据（6 张）**、**分析结果（2 张）**、**辅助（1 张）**。

**基础信息：**

```
stock_info   股票基础信息
etf_info     ETF 基础信息
```

**K 线数据（6 张）：**

```
stock_kline_daily     股票 日 K
stock_kline_weekly    股票 周 K
stock_kline_monthly   股票 月 K
etf_kline_daily       ETF 日 K
etf_kline_weekly      ETF 周 K
etf_kline_monthly     ETF 月 K
```

**分析结果（2 张）：**

```
stock_analysis   股票 技术面分析
etf_analysis     ETF   技术面分析
```

**辅助：**

```
adjust_factor  复权因子
```

> 股票 / ETF 基础信息均由 `query_stock_basic` 返回，靠 `type` 字段区分（股票 `'1'`、ETF `'5'`），分两张表存储。

## 4. 基础信息表（2 张）

### 4.1 股票基础信息 `stock_info`

记录股票（`type='1'`）的基础信息。来自 `query_stock_basic`，其中行业列来自 `query_stock_industry`（该接口仅适用于股票，ETF 无对应数据）。与 K 线表通过 `code` 关联：

```sql
CREATE TABLE IF NOT EXISTS stock_info (
    code                   TEXT PRIMARY KEY,  -- 如 sh.600000
    code_name              TEXT,              -- 证券名称
    market                 TEXT,              -- 市场：SH 上交所 / SZ 深交所（由代码前缀推断）
    type                   TEXT,              -- 证券类型，'1' 股票
    ipoDate                TEXT,              -- 上市日期 YYYY-MM-DD
    outDate                TEXT,              -- 退市日期（在上市为空）
    status                 TEXT,              -- 上市状态，'1' 上市
    updateDate             TEXT,              -- 行业数据更新时间
    industry               TEXT,              -- 所属行业（如 J66 货币金融服务）
    industryClassification TEXT,              -- 行业分类标准（如 证监会行业分类）
    last_trade_date        TEXT,              -- 最后交易日 YYYY-MM-DD
    last_close             REAL,              -- 最后交易日收盘价（不复权）
    last_pct_chg           REAL,              -- 最后交易日涨跌幅（%）
    last_amount            REAL,              -- 最后交易日成交额（元）
    pe_ttm                 REAL               -- 市盈率 PE(TTM)
);
```

> **市场区分**：BaoStock 代码带交易所前缀，`sh.` 为上交所（上海）、`sz.` 为深交所（深圳），`market` 列由前缀推断（`sh`→`SH`、`sz`→`SZ`）。ETF 同样分两个市场（如 `sh.510010` 沪、`sz.159915` 深）。
>
> **新增行情字段的来源（均可从 BaoStock 获取）**：`last_trade_date / last_close / last_pct_chg / last_amount / pe_ttm` 均来自 `query_history_k_data_plus` 的**日 K**（`adjustflag='3'` 不复权），而非 `query_stock_basic`，故可由脚本自动回填，无需 LLM 循环。对应字段映射：`close→last_close`、`pctChg→last_pct_chg`、`amount→last_amount`、`peTTM→pe_ttm`、`date→last_trade_date`（取每个 `code` 日期最大的那一行）。这些字段为**可空**，未回填前为 `NULL`。

### 4.2 ETF 基础信息 `etf_info`

记录 ETF（`type='5'`）的基础信息，字段来自 `query_stock_basic`：

```sql
CREATE TABLE IF NOT EXISTS etf_info (
    code            TEXT PRIMARY KEY,   -- 如 sh.510010
    code_name       TEXT,               -- ETF 名称
    market          TEXT,               -- 市场：SH 上交所 / SZ 深交所（由代码前缀推断）
    type            TEXT,               -- 证券类型，'5' ETF
    ipoDate         TEXT,               -- 上市日期 YYYY-MM-DD
    outDate         TEXT,               -- 退市日期（在上市为空）
    status          TEXT,               -- 上市状态，'1' 上市
    last_trade_date TEXT,               -- 价格对应交易日 YYYY-MM-DD（最后一个有 K 线的交易日）
    last_close      REAL,               -- 最后一个交易日收盘价（不复权原始价），由 LLM 循环填补
    last_pct_chg    REAL,               -- 最后一个交易日涨跌幅（%），由 LLM 循环填补
    fund_scale      REAL                -- 基金规模（如净值规模/份额规模，口径以填补时约定为准），由 LLM 循环填补
);
```

> 说明：BaoStock 没有独立的 ETF 基础信息接口，ETF 也通过 `query_stock_basic` 返回，仅 `type` 取值不同（ETF 为 `'5'`）。
>
> **新增字段说明（LLM 循环填补）**：`last_trade_date` / `last_close` / `last_pct_chg` / `fund_scale` 四个字段并非来自 `query_stock_basic`，而是由外部 LLM 循环根据行情/公开资料逐条补齐：
> - `last_close` / `last_pct_chg`：该 ETF 最后一个交易日（`last_trade_date`）的不复权收盘价与涨跌幅（%），取值可与 `etf_kline_daily` 对应（`adjustflag='3'`）交叉校验。
> - `fund_scale`：基金规模，入库时建议统一口径（如元 / 亿元 / 份额数），并在本文件「约定」中固化，避免后续数据不一致。
> - 这些字段为**可空**，未填补前为 `NULL`。

## 5. K 线表结构（6 张）

### 5.1 股票日 K `stock_kline_daily`

| 列名 | 类型 | 说明 |
|------|------|------|
| `date` | `TEXT` | 交易日 `YYYY-MM-DD` |
| `code` | `TEXT` | 带交易所前缀代码，如 `sh.600000` |
| `open` | `REAL` | 开盘价 |
| `high` | `REAL` | 最高价 |
| `low` | `REAL` | 最低价 |
| `close` | `REAL` | 收盘价 |
| `preclose` | `REAL` | 前收盘价 |
| `volume` | `REAL` | 成交量（股） |
| `amount` | `REAL` | 成交额（元） |
| `adjustflag` | `TEXT` | 复权方式，`'2'` 前复权 / `'3'` 不复权 |
| `turn` | `REAL` | 换手率（%） |
| `tradestatus` | `TEXT` | 交易状态，`'1'` 正常交易 |
| `pctChg` | `REAL` | 涨跌幅（%） |
| `isST` | `TEXT` | 是否 ST，`'1'` 是 / `'0'` 否 |

```sql
CREATE TABLE IF NOT EXISTS stock_kline_daily (
    date        TEXT NOT NULL,
    code        TEXT NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    preclose    REAL,
    volume      REAL,
    amount      REAL,
    adjustflag  TEXT NOT NULL CHECK (adjustflag IN ('2', '3')),
    turn        REAL,
    tradestatus TEXT,
    pctChg      REAL,
    isST        TEXT,
    PRIMARY KEY (code, date, adjustflag)
);
CREATE INDEX IF NOT EXISTS idx_stock_daily_date ON stock_kline_daily(date);
CREATE INDEX IF NOT EXISTS idx_stock_daily_codedate ON stock_kline_daily(code, date);
```

### 5.2 股票周 K `stock_kline_weekly`

BaoStock 周 K **不返回** `preclose`、`tradestatus`、`isST`，故省略这三列：

```sql
CREATE TABLE IF NOT EXISTS stock_kline_weekly (
    date        TEXT NOT NULL,
    code        TEXT NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    volume      REAL,
    amount      REAL,
    adjustflag  TEXT NOT NULL CHECK (adjustflag IN ('2', '3')),
    turn        REAL,
    pctChg      REAL,
    PRIMARY KEY (code, date, adjustflag)
);
CREATE INDEX IF NOT EXISTS idx_stock_weekly_date ON stock_kline_weekly(date);
CREATE INDEX IF NOT EXISTS idx_stock_weekly_codedate ON stock_kline_weekly(code, date);
```

### 5.3 股票月 K `stock_kline_monthly`

```sql
CREATE TABLE IF NOT EXISTS stock_kline_monthly (
    date        TEXT NOT NULL,
    code        TEXT NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    volume      REAL,
    amount      REAL,
    adjustflag  TEXT NOT NULL CHECK (adjustflag IN ('2', '3')),
    turn        REAL,
    pctChg      REAL,
    PRIMARY KEY (code, date, adjustflag)
);
CREATE INDEX IF NOT EXISTS idx_stock_monthly_date ON stock_kline_monthly(date);
CREATE INDEX IF NOT EXISTS idx_stock_monthly_codedate ON stock_kline_monthly(code, date);
```

### 5.4 ETF 日 K `etf_kline_daily`

ETF 日 K 除标准字段外，BaoStock 还返回 **估值指标** `peTTM`、`pbMRQ`、`psTTM`、`pcfNcfTTM`（对多数 ETF 为空字符串）：

```sql
CREATE TABLE IF NOT EXISTS etf_kline_daily (
    date        TEXT NOT NULL,
    code        TEXT NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    preclose    REAL,
    volume      REAL,
    amount      REAL,
    adjustflag  TEXT NOT NULL CHECK (adjustflag IN ('2', '3')),
    turn        REAL,
    tradestatus TEXT,
    pctChg      REAL,
    isST        TEXT,
    peTTM       REAL,
    pbMRQ       REAL,
    psTTM       REAL,
    pcfNcfTTM   REAL,
    PRIMARY KEY (code, date, adjustflag)
);
CREATE INDEX IF NOT EXISTS idx_etf_daily_date ON etf_kline_daily(date);
CREATE INDEX IF NOT EXISTS idx_etf_daily_codedate ON etf_kline_daily(code, date);
```

### 5.5 ETF 周 K `etf_kline_weekly`

```sql
CREATE TABLE IF NOT EXISTS etf_kline_weekly (
    date        TEXT NOT NULL,
    code        TEXT NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    volume      REAL,
    amount      REAL,
    adjustflag  TEXT NOT NULL CHECK (adjustflag IN ('2', '3')),
    turn        REAL,
    pctChg      REAL,
    PRIMARY KEY (code, date, adjustflag)
);
CREATE INDEX IF NOT EXISTS idx_etf_weekly_date ON etf_kline_weekly(date);
CREATE INDEX IF NOT EXISTS idx_etf_weekly_codedate ON etf_kline_weekly(code, date);
```

### 5.6 ETF 月 K `etf_kline_monthly`

```sql
CREATE TABLE IF NOT EXISTS etf_kline_monthly (
    date        TEXT NOT NULL,
    code        TEXT NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    volume      REAL,
    amount      REAL,
    adjustflag  TEXT NOT NULL CHECK (adjustflag IN ('2', '3')),
    turn        REAL,
    pctChg      REAL,
    PRIMARY KEY (code, date, adjustflag)
);
CREATE INDEX IF NOT EXISTS idx_etf_monthly_date ON etf_kline_monthly(date);
CREATE INDEX IF NOT EXISTS idx_etf_monthly_codedate ON etf_kline_monthly(code, date);
```

## 6. 分析结果表（2 张）

基于已有 K 线数据，对股票 / ETF 做纯技术面分析，将**评分、信号与 LLM 分析输出**按时序历史保存，便于回看结论变化与回测验证。默认每周计算一次（权重与频率均可调）。

### 6.1 股票技术面分析 `stock_analysis`

| 列名 | 类型 | 说明 |
|------|------|------|
| `code` | `TEXT` | 证券代码，如 `sh.600000` |
| `date` | `TEXT` | 分析日期 `YYYY-MM-DD` |
| `score` | `REAL` | 综合评分 0~100 |
| `signal` | `TEXT` | 结论：`BUY` / `HOLD` / `SELL` |
| `rating` | `TEXT` | 买入评级（9 档，具时效性，随 `date` 存于分析表）：`S+`/`S`/`A+`/`A`/`B+`/`B`/`C+`/`C`/`D` |
| `is_worth_buying` | `INTEGER` | 是否值得买，0/1（`signal='BUY'` 时=1） |
| `hold_days` | `INTEGER` | 预计持有天数 |
| `ma5` | `REAL` | 5 日均线值 |
| `ma20` | `REAL` | 20 日均线值 |
| `ma60` | `REAL` | 60 日均线值 |
| `trend` | `TEXT` | 趋势：多头 / 空头 / 震荡 |
| `momentum_20` | `REAL` | 近 20 日涨跌幅（%） |
| `volatility_20` | `REAL` | 近 20 日年化波动率（%） |
| `volume_ratio` | `REAL` | 量比（近 5 日均量 / 近 20 日均量） |
| `note` | `TEXT` | 评分理由摘要 |
| `llm_analysis` | `TEXT` | LLM 分析输出的大段文字（自然语言 / Markdown），随历史保存 |

```sql
CREATE TABLE IF NOT EXISTS stock_analysis (
    code            TEXT NOT NULL,
    date            TEXT NOT NULL,
    score           REAL,
    signal          TEXT,
    rating          TEXT,
    is_worth_buying INTEGER,
    hold_days       INTEGER,
    ma5             REAL,
    ma20            REAL,
    ma60            REAL,
    trend           TEXT,
    momentum_20     REAL,
    volatility_20   REAL,
    volume_ratio    REAL,
    note            TEXT,
    llm_analysis    TEXT,
    PRIMARY KEY (code, date)
);
CREATE INDEX IF NOT EXISTS idx_stock_analysis_date ON stock_analysis(date);
```

### 6.2 ETF 技术面分析 `etf_analysis`

结构与 `stock_analysis` 完全一致：

```sql
CREATE TABLE IF NOT EXISTS etf_analysis (
    code            TEXT NOT NULL,
    date            TEXT NOT NULL,
    score           REAL,
    signal          TEXT,
    rating          TEXT,
    is_worth_buying INTEGER,
    hold_days       INTEGER,
    ma5             REAL,
    ma20            REAL,
    ma60            REAL,
    trend           TEXT,
    momentum_20     REAL,
    volatility_20   REAL,
    volume_ratio    REAL,
    note            TEXT,
    llm_analysis    TEXT,
    PRIMARY KEY (code, date)
);
CREATE INDEX IF NOT EXISTS idx_etf_analysis_date ON etf_analysis(date);
```

**评分规则（纯技术面，权重可调）：**

```
score = 0.35×趋势得分 + 0.30×动量得分 + 0.15×波动得分 + 0.20×量能得分
```

- **趋势得分**：MA5>MA20>MA60 多头排列得高分；金叉加分、死叉减分。
- **动量得分**：近 20 日涨幅适中（5%~20%）最高，追高/暴跌压低。
- **波动得分**：年化波动率越低越稳，得分越高。
- **量能得分**：温和放量（量比 1.2~2.5）最佳，缩量/爆量减分。

**结论映射：**

- `score ≥ 65` 且多头趋势 → `signal='BUY'`（`is_worth_buying=1`）
- `45 ≤ score < 65` → `HOLD`
- `score < 45` → `SELL`
- `hold_days`：按趋势强度给出，多头强推持有天数多（如 10~30 天），否则 0

**买入评级（9 档）映射**（纯技术面模式下由 `score` 0~100 换算，阈值可调；LLM 模式下由 LLM 直接产出 `rating`）：

| 区间 | 评级 |
|------|------|
| ≥ 88 | `S+` |
| 75 ~ 87 | `S` |
| 63 ~ 74 | `A+` |
| 50 ~ 62 | `A` |
| 38 ~ 49 | `B+` |
| 25 ~ 37 | `B` |
| 13 ~ 24 | `C+` |
| 6 ~ 12 | `C` |
| < 6 | `D` |

> `rating` 具**时效性**，随 `date` 存于分析表（主键的一部分），**不冗余到 `stock_info` / `etf_info`**。列表页按评级排序时取每只股票最新一条（`code` 分组取最大 `date` 的 `rating`）。

> **LLM 模式**：MVP0 由单个大模型判断是否值得买入并给出持有天数。此时 LLM 的输出应**回填结构字段** `rating`、`is_worth_buying`、`hold_days`（而不是只写入 `llm_analysis` 文字），`llm_analysis` 保存 LLM 的推理文字。纯技术面模式仅作为无 LLM 时的兜底。

## 7. 辅助表

### 7.1 复权因子 `adjust_factor`

存储 `query_adjust_factor` 返回的复权因子，用于在"不复权原始价"基础上现算前/后复权价。当某股发生新除权导致前复权历史价漂移时，用它低成本重算：

```sql
CREATE TABLE IF NOT EXISTS adjust_factor (
    code             TEXT NOT NULL,
    date             TEXT NOT NULL,   -- 除权日期
    foreAdjustFactor REAL,            -- 前复权因子
    backAdjustFactor REAL,            -- 后复权因子
    PRIMARY KEY (code, date)
);
```

> 因子实际含义请以 BaoStock 返回为准（不同 `query_adjust_factor` 调用口径可能返回前复权/后复权因子之一）。重算前复权价的基本思路：`前复权价 ≈ 原始价 × 前复权因子`，具体公式按 BaoStock 文档核对。

## 8. 常用查询示例

```sql
-- 某只股票的前复权日 K（最近 N 天）
SELECT date, open, high, low, close, volume, amount, pctChg
FROM stock_kline_daily
WHERE code = 'sh.600000' AND adjustflag = '2'
ORDER BY date DESC
LIMIT 100;

-- 全市场某交易日所有股票的未复权收盘
SELECT code, close
FROM stock_kline_daily
WHERE date = '2024-01-05' AND adjustflag = '3';

-- 某只 ETF 前复权月 K 全量
SELECT date, open, high, low, close, volume, amount
FROM etf_kline_monthly
WHERE code = 'sh.510010' AND adjustflag = '2'
ORDER BY date;

-- 幂等写入一条日 K（重复则覆盖）
INSERT OR REPLACE INTO stock_kline_daily
  (date, code, open, high, low, close, preclose, volume, amount,
   adjustflag, turn, tradestatus, pctChg, isST)
VALUES
  ('2024-01-05', 'sh.600000', 6.65, 6.67, 6.55, 6.62, 6.64, 28885978, 0,
   '2', 0.0752, '1', -0.3021, '0');

-- LLM 循环按 code 幂等填充 ETF 的收盘价、涨跌幅与规模（未覆盖的列保留原值）
UPDATE etf_info
SET last_trade_date = '2024-01-05',
    last_close = 0.918,
    last_pct_chg = 1.21,
    fund_scale = 530000000.0
WHERE code = 'sh.510010';

-- 用不复权日 K 自动回填 stock_info 的行情字段（按 code 取最大日期一行）
UPDATE stock_info
SET last_trade_date = k.date,
    last_close      = k.close,
    last_pct_chg    = k.pctChg,
    last_amount     = k.amount,
    pe_ttm          = k.peTTM
FROM (
    SELECT code, date, close, pctChg, amount, peTTM,
           ROW_NUMBER() OVER (PARTITION BY code ORDER BY date DESC) AS rn
    FROM stock_kline_daily
    WHERE adjustflag = '3'
) AS k
WHERE stock_info.code = k.code AND k.rn = 1;

-- 查询已有最新收盘价但规模仍为 NULL 的 ETF（供 LLM 循环继续补齐）
SELECT code, code_name, last_trade_date, last_close, fund_scale
FROM etf_info
WHERE last_close IS NOT NULL AND fund_scale IS NULL;

-- 首页统计：收录数量 / 已分析数量 / 已分析次数
SELECT
  (SELECT COUNT(*) FROM stock_info)  AS stock_cnt,
  (SELECT COUNT(*) FROM etf_info)   AS etf_cnt,
  (SELECT COUNT(DISTINCT code) FROM stock_analysis)
    + (SELECT COUNT(DISTINCT code) FROM etf_analysis) AS analyzed_cnt,
  (SELECT COUNT(*) FROM stock_analysis)
    + (SELECT COUNT(*) FROM etf_analysis)             AS analyzed_times;

-- 用 K 线表交叉校验收盘价与涨跌幅（不复权日 K 最后一行的 close / pctChg）
SELECT e.code, e.last_trade_date, e.last_close, e.last_pct_chg,
       k.close AS kline_close, k.pctChg AS kline_pct_chg
FROM etf_info e
JOIN etf_kline_daily k
  ON k.code = e.code
 AND k.date = e.last_trade_date
 AND k.adjustflag = '3';
```

## 9. 写入流程建议

1. `login()` → 用 `query_stock_basic` 分批拉取，按 `type` 区分写入 `stock_info`（`type='1'`）与 `etf_info`（`type='5'`），并可用 `query_stock_industry` 补充股票行业；如需逐日可交易标的，可用 `query_all_stock`。
2. 对每个标的按 日/周/月 和 前复权(`adjustflag='2'`)/不复权(`'3'`) 分别调用 `query_history_k_data_plus`。
3. 将返回 `data` 中的 `str` 数值转 `float`，空串转 `NULL`，`INSERT OR REPLACE` 入库。
4. `commit()` 后可对 `UNIQUE(code, date, adjustflag)` 冲突做 `INSERT OR IGNORE` 增量更新。
5. 对 `etf_info` 中的 `last_trade_date / last_close / last_pct_chg / fund_scale`：由外部 LLM 循环逐条查缺（`fund_scale IS NULL` 等），按 `code` 执行 `UPDATE` 幂等填充；如已有 `last_close`，可先用第 8 节的交叉校验 SQL 核对再写。
6. 结束后 `logout()`。
