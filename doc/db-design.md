# Akshare K 线数据存储设计（SQLite）

本文件描述将 Akshare 的股票 / ETF 日、周、月 K 线数据落库为 SQLite 的数据库设计。
周 / 月 K 由日 K **本地重采样**生成（数据源无直抓接口）。

## 1. 设计目标与原则

- **产品分表**：股票与 ETF **不混在同一张表**，各自独立。
- **频率分表**：日 / 周 / 月 K 各建一张表，避免混合存储造成字段与粒度混乱。
- **复权策略**：每张 K 线表同时保存 **前复权（`adjustflag='2'`）** 与 **不复权原始价（`'3'`）** 两档。
  - 前复权：符合画图 / 趋势分析需求。
  - 不复权：原始成交价“永久真实”。
  - **ETF 仅存不复权（`'3'`）**：新浪源不支持 ETF 复权。
- **幂等写入**：以 `UNIQUE(code, date, adjustflag)` 为主键约束，重复抓取用 `INSERT OR REPLACE` / `INSERT OR IGNORE` 去重。
- **约定**：
  - `code` 存 6 位纯数字（如 `600000`、`510050`），`market` 由代码号段推断。
  - 金额单位统一为**元**（源数据为“亿”/“万”时脚本内换算）。
  - 日期用 `TEXT` 存储，格式 `YYYY-MM-DD`（字典序即时间序）。

## 2. 数据范围与频率说明

| 频率 | 股票范围 | ETF 范围 | 字段集 |
|------|----------|----------|--------|
| 日 K | 新浪源可用历史至今 | 新浪源可用历史至今 | 完整字段（含 `preclose/tradestatus/isST`） |
| 周 K | 同上（日 K 本地重采样） | 同上 | 精简字段 |
| 月 K | 同上（日 K 本地重采样） | 同上 | 精简字段 |

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

> 股票 / ETF 基础信息分别由腾讯全市场行情（`stock_zh_a_spot_tx`）与新浪/同花顺/新浪基金列表写入，靠 `type` 字段区分（股票 `'1'`、ETF `'5'`），分两张表存储。

## 4. 基础信息表（2 张）

### 4.1 股票基础信息 `stock_info`

记录股票（`type='1'`）的基础信息。列表与行情字段由腾讯全市场行情一次写入；
全称/行业/上市日期/市净率/52 周高低由雪球接口逐只补齐（`--fetch-stock-info`）。
与 K 线表通过 `code` 关联：

```sql
CREATE TABLE IF NOT EXISTS stock_info (
    code            TEXT PRIMARY KEY,  -- 如 600000（6 位纯数字）
    code_name       TEXT,              -- 证券名称
    market          TEXT,              -- 市场：SH 上交所 / SZ 深交所（由代码号段推断）
    type            TEXT,              -- 证券类型，'1' 股票
    ipoDate         TEXT,              -- 上市日期 YYYY-MM-DD
    outDate         TEXT,              -- 退市日期（在上市为空；新数据源不提供，恒为 NULL）
    status          TEXT,              -- 上市状态，'1' 上市（新数据源无退市标记，退市股不再出现在列表中）
    industry        TEXT,              -- 所属行业（由 Akshare 填充）
    last_trade_date TEXT,              -- 最后交易日 YYYY-MM-DD
    last_close      REAL,              -- 最后交易日收盘价（不复权）
    last_pct_chg    REAL,              -- 最后交易日涨跌幅（%）
    last_amount     REAL,              -- 最后交易日成交额（元）
    pe_ttm          REAL,              -- 市盈率 PE(TTM)
    pb              REAL,              -- 市净率 PB（由 Akshare 填充）
    full_name       TEXT,              -- 公司全称（由 Akshare 填充）
    total_market_cap REAL,             -- 总市值（元）
    high_52w        REAL,              -- 52 周最高价（由 Akshare 填充）
    low_52w         REAL,              -- 52 周最低价（由 Akshare 填充）
    last_fetch_date TEXT               -- 全量抓取完成日 YYYY-MM-DD（脚本标记，断点续传用）
);
```

> **市场区分**：`code` 为 6 位纯数字，`market` 由号段推断：股票 `60/68` → SH、`00/30` → SZ；ETF `51/56/58` → SH、`15/16` → SZ。
>
> **字段来源**：
> - **腾讯全市场行情（`--update-stock-list`，一次拉全市场）**：`code_name`、`last_trade_date`、`last_close`、`last_pct_chg`、`last_amount`（万→元）、`pe_ttm`、`total_market_cap`（亿→元）。
> - **雪球逐只补齐（`--fetch-stock-info`，仅抓 `full_name` 为空的在市股票）**：`full_name`、`industry`、`ipoDate`、`pb`、`high_52w`、`low_52w`、`total_market_cap`（与腾讯源交叉，后写为准）。这些字段为**可空**，未抓取前为 `NULL`。

### 4.2 ETF 基础信息 `etf_info`

记录 ETF（`type='5'`）的基础信息：

```sql
CREATE TABLE IF NOT EXISTS etf_info (
    code            TEXT PRIMARY KEY,   -- 如 510050（6 位纯数字）
    code_name       TEXT,               -- ETF 名称
    market          TEXT,               -- 市场：SH 上交所 / SZ 深交所（由代码号段推断）
    type            TEXT,               -- 证券类型，'5' ETF
    ipoDate         TEXT,               -- 成立日期 YYYY-MM-DD
    outDate         TEXT,               -- 退市日期（新数据源不提供，恒为 NULL）
    status          TEXT,               -- 上市状态，'1' 上市
    category        TEXT,               -- ETF 类别（股票型/债券型等，同花顺分类），由 Akshare 填充
    manager         TEXT,               -- 基金经理，由 Akshare 填充
    last_trade_date TEXT,               -- 价格对应交易日 YYYY-MM-DD（列表刷新时写入）
    last_close      REAL,               -- 最后一个交易日收盘价（不复权原始价，即 NAV）
    last_pct_chg    REAL,               -- 最后一个交易日涨跌幅（%）
    fund_scale      REAL,               -- 基金募集规模（元），由 Akshare 填充
    last_fetch_date TEXT                -- 全量抓取完成日 YYYY-MM-DD（脚本标记，断点续传用）
);
```

> **字段来源（`--update-etf-list`，三个源批量 join）**：
> - 新浪 `fund_etf_category_sina`：`code`、`code_name`
> - 同花顺 `fund_etf_category_ths`：`category`
> - 新浪基金 `fund_scale_open_sina`：`fund_scale`（万→元）、`manager`、`ipoDate`
> - `last_trade_date / last_close / last_pct_chg` 由 `--update-etf-list` 列表中的实时行情写入（无行情字段时为 `NULL`，可后续由日 K 补齐）。

## 5. K 线表结构（6 张）

### 5.1 股票日 K `stock_kline_daily`

| 列名 | 类型 | 说明 |
|------|------|------|
| `date` | `TEXT` | 交易日 `YYYY-MM-DD` |
| `code` | `TEXT` | 6 位纯数字代码，如 `600000` |
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

周 / 月 K 由日 K 本地重采样生成（数据源无直抓接口），省略 `preclose`、`tradestatus`、`isST` 三列：

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

ETF 日 K 除标准字段外保留 **估值指标** 列 `peTTM`、`pbMRQ`、`psTTM`、`pcfNcfTTM`（新数据源不提供，恒为 `NULL`，保留列以兼容后端）：

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

基于已有 K 线数据，对股票 / ETF 做分析（技术面 + LLM 评分），将**评分、信号与 LLM 分析输出**按 `code + 最后交易日` 保存，便于回看结论变化与回测验证。分析由前端详情页「分析」按钮按需触发，结果幂等 UPSERT（同一天重复分析覆盖更新）。

### 6.1 股票技术面分析 `stock_analysis`

| 列名 | 类型 | 说明 |
|------|------|------|
| `code` | `TEXT` | 证券代码，如 `600000` |
| `date` | `TEXT` | 最后交易日 `YYYY-MM-DD`（取数据最后一行日 K，不用服务器日期，避免 UTC 跨日） |
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
| `note` | `TEXT` | 评分理由摘要（技术指标摘要；LLM 的 `reason` 追加其后） |
| `llm_analysis` | `TEXT` | LLM 分析输出的大段文字（自然语言 / Markdown），随历史保存；LLM 未给 `llmAnalysis` 时用 `reason` 兜底 |
| `dims` | `TEXT` | 实际使用的 5 维得分 JSON（trend/momentum/valuation/volume/stability），用于复现分数 |
| `model` | `TEXT` | 本次分析生效的 LLM 模型（含 env `LLM_MODEL` 覆盖）；技术面降级时为 NULL |
| `prompt_version` | `TEXT` | 提示词模板版本（模板 SHA-1 前 8 位）；技术面降级时为 NULL |

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
    dims            TEXT,
    model           TEXT,
    prompt_version  TEXT,
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
    dims            TEXT,
    model           TEXT,
    prompt_version  TEXT,
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

**买入评级（9 档）映射**（无论 LLM 模式还是技术面降级，`rating` 一律由系统按 `score` 0~100 换算；LLM **不直接产出** `rating`/`signal`/`hold_days`，保证 `score` 与 `rating` 口径一致）：

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

> **LLM 模式**：LLM 只输出 5 维得分（可选 `reason` / `llmAnalysis` 与 info 回填字段），`rating` / `signal` / `is_worth_buying` / `hold_days` 全部由系统按 `compositeScore5` 固定权重换算（见 `backend/src/common/scoring.ts`）。`llm_analysis` 保存 LLM 的推理文字，`reason` 追加进 `note`。**LLM 不可用**（无 API key / 重试耗尽）时降级到纯技术面评分（估值维度给中性 50），任务仍正常完成（`model` / `prompt_version` 为 NULL）。

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

> 复权因子表为历史遗留（原 BaoStock `query_adjust_factor`），迁移后不再写入；新数据源的前复权价直接由新浪 `stock_zh_a_daily(adjust="qfq")` 提供。

### 7.2 分析任务 `analysis_jobs`

分析任务的持久化记录（JobManagerService 双写内存 + 本表，进程重启后仍可查询；重启时中断的 `pending` / `running` 任务标记为 `failed`）：

```sql
CREATE TABLE IF NOT EXISTS analysis_jobs (
    id         TEXT PRIMARY KEY,
    kind       TEXT NOT NULL,           -- 'stock' | 'etf'
    code       TEXT NOT NULL,           -- 标的代码，如 600000
    status     TEXT NOT NULL,           -- pending | running | done | failed
    result     TEXT,                    -- 任务结果（JSON 序列化，done 时）
    error      TEXT,                    -- 失败原因
    created_at TEXT NOT NULL,           -- 创建时间（ISO 8601）
    updated_at TEXT NOT NULL            -- 最近更新时间（ISO 8601）
);
CREATE INDEX IF NOT EXISTS idx_analysis_jobs_code ON analysis_jobs(kind, code, status);
```

> 调度规则：同一标的同一时刻只允许一个 `pending` / `running` 任务（per-code 去重）；全局并发上限 3（信号量，FIFO 排队）。

## 8. 常用查询示例

```sql
-- 某只股票的前复权日 K（最近 N 天）
SELECT date, open, high, low, close, volume, amount, pctChg
FROM stock_kline_daily
WHERE code = '600000' AND adjustflag = '2'
ORDER BY date DESC
LIMIT 100;

-- 全市场某交易日所有股票的未复权收盘
SELECT code, close
FROM stock_kline_daily
WHERE date = '2024-01-05' AND adjustflag = '3';

-- 某只 ETF 不复权月 K 全量（ETF 仅存不复权）
SELECT date, open, high, low, close, volume, amount
FROM etf_kline_monthly
WHERE code = '510010' AND adjustflag = '3'
ORDER BY date;

-- 幂等写入一条日 K（重复则覆盖）
INSERT OR REPLACE INTO stock_kline_daily
  (date, code, open, high, low, close, preclose, volume, amount,
   adjustflag, turn, tradestatus, pctChg, isST)
VALUES
  ('2024-01-05', '600000', 6.65, 6.67, 6.55, 6.62, 6.64, 28885978, 0,
   '2', 0.0752, '1', -0.3021, '0');

-- 查询个股字段尚未补齐的股票（供 --fetch-stock-info 继续补齐）
SELECT code, code_name FROM stock_info
WHERE status = '1' AND (full_name IS NULL OR full_name = '');

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

## 9. 写入流程（scripts/fetch_data.py）

| 命令 | 写入内容 | 数据源 |
|------|----------|--------|
| `--update-stock-list` | stock_info 列表 + 行情字段 | 腾讯 `stock_zh_a_spot_tx`（一次拉全市场） |
| `--update-etf-list` | etf_info 列表/类别/规模/管理人 | 新浪 + 同花顺 + 新浪基金（均批量） |
| `--fetch-stock-info` | stock_info 个股补齐字段（仅未抓过的） | 雪球逐只（限速 + 断点续传） |
| `--fetch-stock-kline` | 股票日/周/月 K（周/月本地重采样） | 新浪 `stock_zh_a_daily` |
| `--fetch-etf-kline` | ETF 日/周/月 K（仅不复权） | 新浪 `fund_etf_hist_sina` |

抓取计划：

| 任务 | 频率 |
|------|------|
| 列表刷新 + daily 增量（`--incremental`） | 每交易日 |
| weekly/monthly 增量 | 随 daily 跑，由频率门控决定 |
| `--fetch-stock-info` | 每周一次或手动 |

增量门控：daily 仅工作日；weekly 周末且未入库或距今超 7 天；monthly 月初前 3 天或距今超 31 天。
限速与容错：串行 + `--sleep`（默认 0.5）+ 指数退避重试（默认 3 次，1s/4s/16s）；单只失败记日志继续，不中断全量任务。
