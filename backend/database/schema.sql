-- next-choice SQLite 数据库 schema
-- 与 doc/db-design.md 保持一致（14 张表：基础信息 2 / K线 6 / 分析 2 / 辅助 4）
-- 由 scripts/db.py 读取执行建表，未来 Nest.js 后端复用同一文件，避免 SQL 漂移。

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ============ 基础信息 ============

CREATE TABLE IF NOT EXISTS stock_info (
    code            TEXT PRIMARY KEY,  -- 如 600000（6 位纯数字）
    code_name       TEXT,
    market          TEXT,              -- SH / SZ（由代码号段推断）
    type            TEXT,              -- '1' 股票
    ipoDate         TEXT,
    outDate         TEXT,
    status          TEXT,              -- '1' 上市
    industry        TEXT,              -- 由 Akshare 填充
    last_trade_date TEXT,
    last_close      REAL,
    last_pct_chg    REAL,
    last_amount     REAL,
    pe_ttm          REAL,
    pb              REAL,
    full_name       TEXT,
    total_market_cap REAL,
    high_52w        REAL,
    low_52w         REAL,
    last_fetch_date TEXT             -- 全量抓取完成日（脚本标记，断点续传用）
);

CREATE TABLE IF NOT EXISTS etf_info (
    code            TEXT PRIMARY KEY,   -- 如 510050（6 位纯数字）
    code_name       TEXT,
    market          TEXT,               -- SH / SZ（由代码号段推断）
    type            TEXT,               -- '5' ETF
    ipoDate         TEXT,
    outDate         TEXT,
    status          TEXT,               -- '1' 上市
    category        TEXT,               -- 由 Akshare 填充
    manager         TEXT,               -- 由 Akshare 填充
    last_trade_date TEXT,
    last_close      REAL,
    last_pct_chg    REAL,
    fund_scale      REAL,               -- 由 Akshare 填充
    high_52w        REAL,               -- 雪球逐只补齐
    low_52w         REAL,               -- 雪球逐只补齐
    last_fetch_date TEXT                -- 全量抓取完成日（脚本标记，断点续传用）
);

-- ============ K 线数据 ============

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

-- ============ 分析结果 ============

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
    dims            TEXT,               -- 5 维得分 JSON（trend/momentum/valuation/volume/stability）
    model           TEXT,               -- 本次分析所用 LLM 模型（技术面降级时为 NULL）
    prompt_version  TEXT,               -- 提示词模板版本（模板内容 SHA-1 前 8 位）
    PRIMARY KEY (code, date)
);
CREATE INDEX IF NOT EXISTS idx_stock_analysis_date ON stock_analysis(date);

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
    dims            TEXT,               -- 5 维得分 JSON（trend/momentum/valuation/volume/stability）
    model           TEXT,               -- 本次分析所用 LLM 模型（技术面降级时为 NULL）
    prompt_version  TEXT,               -- 提示词模板版本（模板内容 SHA-1 前 8 位）
    PRIMARY KEY (code, date)
);
CREATE INDEX IF NOT EXISTS idx_etf_analysis_date ON etf_analysis(date);

-- ============ 辅助 ============
CREATE TABLE IF NOT EXISTS adjust_factor (
    code             TEXT NOT NULL,
    date             TEXT NOT NULL,   -- 除权日期
    foreAdjustFactor REAL,
    backAdjustFactor REAL,
    PRIMARY KEY (code, date)
);

-- 分析配置（LLM 提示词等）的 DB 覆盖（llm-analysis.md §4 方案 A）。
-- 默认值在 backend/src/config/analysis.config.json；此处仅存 DB 覆盖项。
CREATE TABLE IF NOT EXISTS analysis_config (
    key        TEXT PRIMARY KEY,
    value      TEXT,      -- JSON 字符串
    updated_at TEXT
);

-- info 补齐尝试计数：数据源本就没有某只证券的字段时（雪球对部分标的
-- 不返回 52 周高低/全称），不计数就会每轮全量重试。达到上限的证券在
-- --fetch-stock-info / --fetch-etf-info 中跳过，--force 可忽略上限。
CREATE TABLE IF NOT EXISTS info_backfill_attempts (
    kind         TEXT NOT NULL,           -- 'stock' | 'etf'
    code         TEXT NOT NULL,
    attempts     INTEGER NOT NULL DEFAULT 0,
    last_attempt TEXT,                    -- 最近一次尝试日期
    PRIMARY KEY (kind, code)
);

-- 分析任务（JobManagerService 落库，进程重启后仍可查询/恢复）。
CREATE TABLE IF NOT EXISTS analysis_jobs (
    id         TEXT PRIMARY KEY,
    kind       TEXT NOT NULL,           -- 'stock' | 'etf'
    code       TEXT NOT NULL,           -- 标的代码，如 sh.600000
    status     TEXT NOT NULL,           -- pending | running | done | failed
    result     TEXT,                    -- 任务结果（JSON 序列化，done 时）
    error      TEXT,                    -- 失败原因
    created_at TEXT NOT NULL,           -- 创建时间（ISO 8601）
    updated_at TEXT NOT NULL            -- 最近更新时间（ISO 8601）
);
CREATE INDEX IF NOT EXISTS idx_analysis_jobs_code ON analysis_jobs(kind, code, status);

-- ============ 索引清理 ============
-- 主键 (code, date, adjustflag) 的自动索引，其 (code, date) 前缀已覆盖
-- 这些索引原本服务的查询，留着只是给全库最大的 6 张 K 线表白付写放大。
-- 建表用 IF NOT EXISTS，旧库不会自动少掉索引，故在此显式 DROP（幂等）。
DROP INDEX IF EXISTS idx_stock_daily_codedate;
DROP INDEX IF EXISTS idx_stock_weekly_codedate;
DROP INDEX IF EXISTS idx_stock_monthly_codedate;
DROP INDEX IF EXISTS idx_etf_daily_codedate;
DROP INDEX IF EXISTS idx_etf_weekly_codedate;
DROP INDEX IF EXISTS idx_etf_monthly_codedate;
