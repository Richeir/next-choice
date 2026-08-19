# 数据采集脚本（BaoStock -> SQLite）

独立 Python 脚本，从 BaoStock 拉取证券基础信息与 K 线写入本地 SQLite。
数据库 schema 单一定义于 `backend/database/schema.sql`（与 Nest.js 后端共用）。

## 环境

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 用法

```bash
# 股票 + ETF，日/周/月 K，前复权 + 不复权，指定日期区间
python fetch_data.py --db ../data/market.db \
    --codes sh.600000,sz.159915 \
    --freq daily,weekly,monthly --adjust 2,3 \
    --start 2024-01-01 --end 2024-01-31

# 仅拉取当日全部 ETF 列表并写入 etf_info（不带 K 线，每 100 只批量落库并打印进度）
python fetch_data.py --update-etf-list [--list-date 2026-08-17]

# 仅拉取当日全部 A 股列表并写入 stock_info（不带 K 线，每 100 只批量落库并打印进度）
python fetch_data.py --update-stock-list [--list-date 2026-08-17]

# 根据 etf_info 表全量抓取 ETF 的日/周/月 K 线（先跑 --update-etf-list
# 填充 etf_info；默认复权 2,3（前复权+不复权），--start 控制起始日）
python fetch_data.py --db ../data/market.db --fetch-etf-kline \
    --freq daily,weekly,monthly --start 2026-01-05

# 根据 stock_info 表全量抓取 A 股的日/周/月 K 线（先跑 --update-stock-list
# 填充 stock_info；默认复权 2,3（前复权+不复权），--start 控制起始日；
# 支持断点续传：三档全部成功才标记 last_fetch_date=今天，重跑跳过已标记的）
python fetch_data.py --db ../data/market.db --fetch-stock-kline \
    --freq daily,weekly,monthly --start 2026-01-05

# 日常增量更新（需已有全量数据）：从每只证券最后一根 K 线日期开始抓，
# 并按频率门控（见下方「增量更新」节；股票/ETF 同理）
python fetch_data.py --db ../data/market.db --fetch-stock-kline \
    --freq daily,weekly,monthly --incremental
```

参数说明：

| 参数 | 必填 | 默认 | 说明 |
|------|------|------|------|
| `--db` | 否 | `../data/market.db` | SQLite 数据库路径 |
| `--codes` | 二选一 | — | 逗号分隔证券代码，如 `sh.600000,sz.159915`；与 `--update-etf-list` / `--update-stock-list` 互斥 |
| `--update-etf-list` | 三选一 | — | 拉取当日全部 ETF 基础信息写入 `etf_info` 表 |
| `--update-stock-list` | 三选一 | — | 拉取当日全部 A 股基础信息写入 `stock_info` 表 |
| `--fetch-etf-kline` | 四选一 | — | 根据 `etf_info` 表全量抓取 ETF 日/周/月 K 线（需先跑 `--update-etf-list`） |
| `--fetch-stock-kline` | 四选一 | — | 根据 `stock_info` 表全量抓取 A 股日/周/月 K 线（需先跑 `--update-stock-list`） |
| `--list-date` | 否 | 今天 | `--update-etf-list` / `--update-stock-list` 使用的日期 `YYYY-MM-DD` |
| `--force` | 否 | `False` | 忽略 `last_fetch_date` 标记，强制全量重抓（供换日期窗口等场景） |
| `--incremental` | 否 | `False` | 日常增量更新：从每只证券最后一根 K 线日期开始抓，并按频率门控；仅限 `--fetch-stock-kline` / `--fetch-etf-kline`；与 `--force` 组合时忽略完成标记但门控仍生效 |
| `--timeout` | 否 | `30` | 网络请求超时秒数，`0` 禁用超时（请求卡住到点自动失败并继续） |
| `--freq` | 否 | `daily` | 逗号分隔频率：`daily,weekly,monthly` |
| `--adjust` | 否 | `3`（`--codes`）/ `2,3`（`--fetch-etf-kline`） | 逗号分隔复权：`2`(前复权) / `3`(不复权) |
| `--start` | 否 | 回溯 5 年 | 起始日期 `YYYY-MM-DD`，缺省为 `--end` 往前 5 年 |
| `--end` | 否 | 今天 | 结束日期 `YYYY-MM-DD`，缺省为当天 |

> **默认回溯窗口**：文档未定义采集默认回溯天数，脚本约定未指定 `--start` 时回溯 **5 年**（`end` 缺省为今天）。
>
> 注意：ETF 的 K 线数据范围自 **2026-01-05** 起；股票自 1990-12-19 起。
> 复权因子表 `adjust_factor` 当前由脚本按需写入（可扩展 `--factors`）。

## 流程

1. `login()` 登录
2. 逐个 code 用 `query_stock_basic` 写 `stock_info`（type='1'）/ `etf_info`（type='5'）
3. 逐个 (code, freq, adjustflag) 用 `query_history_k_data_plus` 幂等写 K 线
   （`INSERT OR REPLACE`，主键 `UNIQUE(code, date, adjustflag)`）
4. 用不复权日 K 回填 `last_trade_date / last_close / last_pct_chg`
5. `logout()` 登出

> `--update-etf-list` / `--update-stock-list` 走旁路：仅拉列表接口
> （`query_daily_history_k_ETF` / `query_daily_history_k_AStock`）拿全部代码，
> 再逐只 `query_stock_basic` 补齐基础信息写入 `etf_info` / `stock_info`，
> 不拉 K 线。`--fetch-etf-kline` / `--fetch-stock-kline` 则分别从
> `etf_info` / `stock_info` 表读全部 code，逐个抓 `daily/weekly/monthly` × 复权
> 组合的 K 线（不重新查询列表接口），默认同时写前复权(`2`)与不复权(`3`)两档，
> 结束后回填对应行情字段；单只失败记 warning 不中断整体，每只打印进度。

## 增量更新（`--incremental`）

全量入库后的日常更新用 `--incremental`（仅限 `--fetch-stock-kline` /
`--fetch-etf-kline`），避免每次都重拉 5 年窗口：

- **起始日期**：每只证券、每个频率从 DB 中最后一根 K 线的日期开始重拉
  （重拉最后一天以覆盖可能的数据修正，`INSERT OR REPLACE` 幂等去重）；
  表里没数据的新证券回退到 `--start` / 默认 5 年窗口补全。
- **跳过判断**：`last_fetch_date == 今天` 的证券直接跳过（同一天重跑不会重复请求）；
  退市（`status='0'`）证券不会再有新数据，增量模式也直接跳过（全量模式不跳过）。
- **频率门控**（仅对已有数据的频率生效；无数据的新证券不门控直接补全）：

  | 频率 | 何时更新 |
  |------|----------|
  | daily | 仅周一～周五（周末不开盘；节后靠最后日期自动补齐） |
  | weekly | 周六/周日且最后周 K 距今 >2 天（周 K 周六生成；周六入库后周日不重抓，周六未抓到时周日重试），**或** 最后一根周 K 距今 >7 天（补漏） |
  | monthly | 月初前 3 天（`day <= 3`），**或** 最后一根月 K 距今 >31 天（补漏） |

- **完成标记**：本轮“应更”频率全部成功才标记 `last_fetch_date = 今天`
  （被门控跳过的频率不阻塞标记；失败的证券不标记，重跑可继续）。
- **与 `--force` 组合**：`--force` 只忽略 `last_fetch_date` 跳过标记（重新处理
  全部证券），频率门控与“从最后日期开始抓”的增量起点仍然生效；需要换日期
  窗口全量重抓时请勿加 `--incremental`。

典型 cron 安排：每天收盘后跑一次 `--fetch-stock-kline --incremental` 和
`--fetch-etf-kline --incremental` 即可——工作日自动只更日 K，周六/周日只更周 K，
月初额外更月 K。

## 断点续传与超时

- **断点续传**：全量抓取支持断点续传。某证券只有当本次请求覆盖**全部三档**
  （`daily`+`weekly`+`monthly`）且所有 `(freq, adjust)` 组合都成功时，才会把
  `stock_info` / `etf_info` 的 `last_fetch_date` 标记为**当天**；重跑时
  `last_fetch_date == 当天` 的证券直接跳过。这样中断后重跑不会重复抓已完成的证券。
  - 注意：只跑单档（如 `--freq daily`）时**不会**标记，下次跑三档会重抓该档以补全。
  - 换日期窗口等需要强制重抓的场景，用 `--force`。
- **请求超时**：默认给 baostock 全局 socket 设 30s 超时，挂起的请求到点自动失败并
  记 `fail` 继续，不再无限卡住；可用 `--timeout` 调整（`0` 禁用）。超时后会话可能
  失效导致后续连续失败，此时重启程序配合断点续传即可继续。

## 测试

```bash
source .venv/bin/activate

# 仅单元测试（不打网络，快）
python -m pytest tests -q -m "not e2e"

# 全部（含 E2E，真实连接 BaoStock，拉少量数据）
python -m pytest tests -q
```

- `tests/test_transform.py`：数据转换 / 市场推断 / 表名映射
- `tests/test_db.py`：建表（12 张）、幂等写入、行情回填（临时库）
- `tests/test_fetch.py`：`fetch_data` 纯逻辑（K 线字段、日期窗口）
- `tests/test_fetch_etf_list.py`：`update_etf_list` + CLI 解析（mock BaoStock）
- `tests/test_fetch_etf_kline.py`：`fetch_etf_kline` 全量 K 线抓取 + 默认复权（mock BaoStock）
- `tests/test_fetch_stock_kline.py`：`fetch_stock_kline` 全量 K 线抓取 + 默认复权（mock BaoStock）
- `tests/test_fetch_stock_list.py`：`update_stock_list` + CLI 解析（mock BaoStock）
- `tests/test_fetch_incremental.py`：`--incremental` 增量模式：起始日期 / 频率门控 /
  跳过与标记逻辑（mock BaoStock）
- `tests/test_e2e.py`：真实 BaoStock 拉取小样本入库 + 回填的端到端验证
