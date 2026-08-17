-- next-choice SQLite 数据库 schema
-- 与 doc/db-design.md 保持一致（11 张表：基础信息 2 / K线 6 / 分析 2 / 辅助 1）
-- 由 scripts/db.py 读取执行建表，未来 Nest.js 后端复用同一文件，避免 SQL 漂移。

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ============ 基础信息 ============

CREATE TABLE IF NOT EXISTS stock_info (
    code            TEXT PRIMARY KEY,  -- 如 sh.600000
    code_name       TEXT,
    market          TEXT,              -- SH / SZ（由代码前缀推断）
    type            TEXT,              -- '1' 股票
    ipoDate         TEXT,
    outDate         TEXT,
    status          TEXT,              -- '1' 上市
    industry        TEXT,              -- 由 LLM 填充
    last_trade_date TEXT,
    last_close      REAL,
    last_pct_chg    REAL,
    last_amount     REAL,
    pe_ttm          REAL,
    pb              REAL,
    full_name       TEXT,
    total_market_cap REAL,
    high_52w        REAL,
    low_52w         REAL
);

CREATE TABLE IF NOT EXISTS etf_info (
    code            TEXT PRIMARY KEY,   -- 如 sh.510010
    code_name       TEXT,
    market          TEXT,               -- SH / SZ
    type            TEXT,               -- '5' ETF
    ipoDate         TEXT,
    outDate         TEXT,
    status          TEXT,               -- '1' 上市
    category        TEXT,               -- 由 LLM 填充
    manager         TEXT,               -- 由 LLM 填充
    last_trade_date TEXT,
    last_close      REAL,
    last_pct_chg    REAL,
    fund_scale      REAL                -- 由 LLM 填充
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
CREATE INDEX IF NOT EXISTS idx_stock_daily_codedate ON stock_kline_daily(code, date);

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
