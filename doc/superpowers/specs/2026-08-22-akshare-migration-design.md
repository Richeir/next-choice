# 数据源重构：BaoStock → Akshare（Issue #32）

- 状态：设计已确认
- 日期：2026-08-22
- 范围：`scripts/`、`backend/database/schema.sql`、`doc/`

## 1. 背景与目标

BaoStock 数据内容少（行业、估值、全称、ETF 管理人/规模等缺失，需 LLM
回填）。本次重构将数据源完全替换为 Akshare：

- **完全移除 BaoStock**，不保留备用源
- **完全移除 LLM 回填**（删除 `llm_backfill.py`），所有字段改为直抓
- schema 的 `code` 改为 Akshare 风格（6 位纯数字）
- 现有 `data/market.db` 直接删除重建（用户已备份）
- 抓取策略：串行 + 可配置 sleep + 失败重试退避，不给上游站点添麻烦

## 2. Spike 结论：可用数据源（2026-08-22 实测）

**东财（EM）系接口在当前网络环境不可用**（多次重试均
`RemoteDisconnected`），本设计全部采用腾讯 / 新浪 / 雪球 / 同花顺源：

| 需求 | 接口 | 实测 |
|------|------|------|
| A 股列表 + pe_ttm/总市值/现价/成交额 | `stock_zh_a_spot_tx`（腾讯） | 5549 只 / ~12s |
| 股票日 K（不复权/前复权/后复权） | `stock_zh_a_daily`（新浪） | ✅ |
| 股票周/月 K | 无直抓源，由日 K 本地重采样 | — |
| 全称 / 行业 / IPO 日期 | `stock_individual_basic_info_xq`（雪球） | ✅（逐只） |
| PB / 52 周高低 / 市值 | `stock_individual_spot_xq`（雪球） | ✅（逐只） |
| ETF 列表 | `fund_etf_category_sina`（新浪） | 1636 只 |
| ETF 日 K（仅不复权） | `fund_etf_hist_sina`（新浪） | ✅ |
| ETF 类别 | `fund_etf_category_ths`（同花顺） | ✅ |
| ETF 规模 / 管理人 / 成立日期 | `fund_scale_open_sina`（新浪） | 6908 只 |

原 10 个 LLM 回填字段全部有直抓来源。

## 3. Schema 变更

`backend/database/schema.sql` 仍是单一来源。

- `code` 格式：`sh.600000` → `600000`。`market` 由号段推断：
  - 股票：`60/68` → SH，`00/30` → SZ
  - ETF：`51/56/58` → SH，`15/16` → SZ
- 移除 `stock_info.llm_backfill_at`、`etf_info.llm_backfill_at`
- `industry` / `category` / `manager` / `fund_scale` 等列保留，注释改为
  "由 Akshare 填充"
- `last_fetch_date` 保留（断点续传）
- K 线 6 张表结构不变；`adjustflag` 语义保持项目现有约定：`'2'` 前复权 /
  `'3'` 不复权（schema CHECK 不变）；新浪源映射：`qfq` → `'2'`，
  不复权（`""`）→ `'3'`
- 新浪不支持 ETF 复权：`etf_kline_*` 只写入 `adjustflag='3'`
- ETF 日 K 无 peTTM/pbMRQ/psTTM/pcfNcfTTM 来源：这些列写 NULL（列保留）
- 金额单位统一为**元**（腾讯源"亿" × 1e8 换算）

## 4. 架构：新增数据源层（方案 B）

### 4.1 `scripts/akshare_source.py`（新增）

封装所有 Akshare 调用，输出标准化结构，不感知 SQLite。

```
akshare_source.py
├── 基础设施
│   ├── fetch_with_retry(fn, ...)   指数退避（1s/4s/16s），仅网络异常重试，
│   │                               重试次数可配置
│   └── sleep_between(seconds)      逐只抓取限速（默认 0.5s）
├── 列表类（全市场一次拉取）
│   ├── list_stocks()      code/name/pe_ttm/总市值/现价/成交额（腾讯）
│   ├── list_etfs()        code/name（新浪）
│   ├── etf_category_map() code → category（同花顺）
│   └── fund_scale_map()   code → scale/manager/establish_date（新浪基金）
├── 个股逐只类（限速 + 断点续传）
│   ├── stock_basic(code)  full_name/industry/ipo_date（雪球）
│   └── stock_quote(code)  pb/high_52w/low_52w/total_market_cap（雪球）
└── K 线类
    ├── stock_kline(code, start, end, adjust)  新浪日 K
    ├── etf_kline(code, start, end)            新浪日 K（不复权）
    └── resample(df, freq)                     日 K → 周/月
```

设计要点：

1. 周/月 K 由日 K 本地重采样（open 首值、close 尾值、high max、
   low min、volume/amount 求和）
2. `preclose` 派生：上一根 close，首根为 NULL
3. 代码格式转换内聚本层：新浪 `sh600000`、雪球 `SH600000`、
   腾讯 `sh600000` ↔ 存储 6 位纯数字
4. 重试耗尽返回 `None` + 日志，上层跳过继续，不中断全量任务

### 4.2 `scripts/fetch_data.py`（重写）

CLI 命令结构保持：

| 命令 | 行为 |
|------|------|
| `--update-stock-list` | 腾讯全量刷新列表 + 行情字段 |
| `--fetch-stock-info`（新增） | 雪球逐只抓 full_name/industry/ipoDate/pb/52 周高低，断点续传 |
| `--update-etf-list` | 新浪+同花顺+新浪基金批量刷新列表/类别/规模/管理人 |
| `--fetch-stock-kline` / `--fetch-etf-kline` | 逐只抓日 K，周/月本地重采样；沿用 `--freq/--adjust/--start/--incremental` |

增量门控保持不变：

- daily：仅工作日
- weekly：周末且未入库或距今超 7 天
- monthly：月初前 3 天或距今超 31 天

新增参数：`--sleep`（默认 0.5）、`--max-retries`（默认 3）、
`--fetch-stock-info` 支持 `--limit`（限制处理数量，便于分批/试跑）。
删除 `bs.login()/logout()` 及所有旧回填逻辑。

## 5. 抓取计划

| 任务 | 频率 | 说明 |
|------|------|------|
| 列表刷新 + daily 增量 | 每交易日 | 腾讯全量 + 逐只日 K |
| weekly/monthly 增量 | 随 daily 跑 | 由门控决定，无额外调度 |
| `--fetch-stock-info` | 每周一次或手动 | ~5400 只预计 1-2 小时，只抓未抓过的 |

## 6. 清理

- 删除 `scripts/llm_backfill.py` 及其测试
- `scripts/transform.py` 保留：`market_of` 改为号段推断；`to_float` 增加
  NaN 处理；`kline_table` 不变（`db.py` 依赖）
- `scripts/db.py`：删除 `backfill_stock_info`/`backfill_etf_info`
  （行情字段改由列表刷新时从腾讯 spot 直接写入）
- `requirements.txt`：移除 `baostock`，加入 `akshare`

## 7. 文档更新（`doc/`）

| 文件 | 变更 |
|------|------|
| `doc/baostock-api.md` | 重写为 `doc/akshare-api.md`：实际使用的接口清单、来源站点、已知限制（EM 不可用、ETF 无复权） |
| `doc/db-design.md` | code 格式、移除的列、单位约定 |
| `doc/architecture.md` | 数据流图更新，删除 LLM 回填环节 |
| `doc/llm-analysis.md` | 删除"LLM 回填基础信息"章节（分析打分不受影响） |
| `doc/tech-stack.md` / `doc/README.md` / `scripts/README.md` | 依赖与用法更新 |

## 8. 测试与验证

- `akshare_source.py`：重采样、代码转换、单位换算、重试逻辑用
  pytest 覆盖（纯函数）
- `fetch_data.py`：内存 SQLite + mock 数据源测试入库编排
- 网络接口不做自动化测试，手动冒烟
- 后端测试套件仅更新 fixture 中的示例代码格式（源码无硬编码格式）

验证标准：

1. 删库重建后 `--update-stock-list` + `--fetch-stock-info --limit 10`
   + 单只全频率 K 线跑通
2. `--incremental` 门控逻辑测试通过
3. 后端测试套件通过
