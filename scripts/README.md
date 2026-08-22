# 数据采集脚本（Akshare -> SQLite）

独立 Python 脚本，从 Akshare（腾讯/新浪/雪球/同花顺源，东财源在当前网络
不可用）拉取证券基础信息与 K 线写入本地 SQLite。接口清单与已知限制见
[../doc/akshare-api.md](../doc/akshare-api.md)。

## 环境

```bash
cd scripts
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

## 快速开始

```bash
cd scripts

# 1. 全量刷新 A 股列表 + 实时行情字段（腾讯，一次拉全市场）
.venv/bin/python fetch_data.py --db ../data/market.db --update-stock-list

# 2. 全量刷新 ETF 列表 + 类别/规模/管理人
.venv/bin/python fetch_data.py --db ../data/market.db --update-etf-list

# 3. 雪球逐只补齐个股字段（全称/行业/IPO/PB/52周），只处理未抓过的
.venv/bin/python fetch_data.py --db ../data/market.db --fetch-stock-info --limit 10

# 4. 雪球逐只补齐 ETF 字段（52周高低），只处理未抓过的
.venv/bin/python fetch_data.py --db ../data/market.db --fetch-etf-info --limit 10

# 5. 按 stock_info 全量抓 A 股 K 线（周/月由日 K 本地重采样）
.venv/bin/python fetch_data.py --db ../data/market.db --fetch-stock-kline \
    --freq daily,weekly,monthly --adjust 2,3 --start 2026-01-05

# 6. ETF K 线（仅不复权，--adjust 会被强制为 3）
.venv/bin/python fetch_data.py --db ../data/market.db --fetch-etf-kline \
    --freq daily,weekly,monthly --start 2026-01-05

# 7. 日常增量（从每只证券最后一根 K 线日期开始，按频率门控）
.venv/bin/python fetch_data.py --db ../data/market.db --fetch-stock-kline \
    --freq daily,weekly,monthly --incremental

# 8. 指定代码抓取（6 位纯数字，自动补 info 行）
.venv/bin/python fetch_data.py --db ../data/market.db \
    --codes 600000,510050 --freq daily,weekly,monthly --start 2024-01-01
```

## 命令一览

| 命令 | 说明 | 数据源 |
|------|------|--------|
| `--update-stock-list` | 刷新 A 股列表与行情字段 | 腾讯 `stock_zh_a_spot_tx` |
| `--update-etf-list` | 刷新 ETF 列表/类别/规模/管理人 | 新浪 + 同花顺 + 新浪基金 |
| `--fetch-stock-info [--limit N]` | 补齐个股字段（仅 `full_name` 为空的） | 雪球（逐只） |
| `--fetch-etf-info [--limit N]` | 补齐 ETF 52周高低（仅 `high_52w` 为空的） | 雪球（逐只） |
| `--fetch-stock-kline` | 抓 A 股 K 线 | 新浪日 K + 本地重采样 |
| `--fetch-etf-kline` | 抓 ETF K 线（仅不复权） | 新浪日 K + 本地重采样 |
| `--codes 600000,...` | 指定代码抓取 | 同上 |

通用参数：

- `--freq daily,weekly,monthly`：频率（默认 `daily`）
- `--adjust 2,3`：`2` 前复权 / `3` 不复权（K 线命令缺省 `2,3`，`--codes` 缺省 `3`；ETF 恒 `3`）
- `--start / --end`：日期窗口（缺省回溯 5 年）
- `--sleep 0.5`：逐只抓取间隔秒数
- `--max-retries 3`：网络重试次数（指数退避 1s/4s/16s）
- `--force`：忽略 `last_fetch_date` 断点标记
- `--incremental`：增量模式（仅 `--fetch-*-kline`）

## 增量门控规则

- **daily**：仅工作日
- **weekly**：周末且最后周 K 距今 >2 天，或距今 >7 天（补漏）
- **monthly**：月初前 3 天，或距今 >31 天（补漏）

## 断点续传

全量模式要求日/周/月三档全部成功才把该证券的 `last_fetch_date` 标记为
今天；重跑同一命令会跳过已标记的证券。`--force` 忽略标记。

## 文件说明

| 文件 | 职责 |
|------|------|
| `fetch_data.py` | CLI 与抓取编排 |
| `akshare_source.py` | Akshare 数据源层：重试限速、代码格式转换、单位换算、日 K 规整与周/月重采样 |
| `db.py` | SQLite 建库与幂等写入（schema 来源 `backend/database/schema.sql`） |
| `transform.py` | 类型清洗、市场号段推断、K 线表名 |

## 测试

```bash
cd scripts
# 单元测试（全部离线，mock 网络）
.venv/bin/python -m pytest tests/ -v

# 含真实网络冒烟（拉少量真实数据）
.venv/bin/python -m pytest tests/ -v -m e2e
```
