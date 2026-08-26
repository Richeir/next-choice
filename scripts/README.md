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
- `--max-retries 3`：瞬时故障重试次数（指数退避 1s/4s/16s，带 ±50% 随机抖动）
- `--force`：忽略 `last_fetch_date` 断点标记与 info 补齐尝试上限
- `--incremental`：增量模式（仅 `--fetch-*-kline`）

`--freq` / `--adjust` 在参数解析阶段就校验，`--freq daly` / `--adjust 1`
这类笔误会立刻报错退出，不会跑到抓取循环深处才失败、白花请求配额。

日志通过 `logging.basicConfig` 输出到 stderr，级别可用环境变量
`LOG_LEVEL`（默认 `INFO`）调整。

## 环境变量

- `LOG_LEVEL`：日志级别，默认 `INFO`。
- `XQ_TOKEN`：雪球 `xq_a_token`（issue #55）。akshare 内置 token 已过期
  （`error 400016`），不配置则 `--fetch-stock-info` / `--fetch-etf-info`
  的雪球调用全部失败（K 线抓取不受影响）。获取：浏览器登录 xueqiu.com，
  从 DevTools -> Application -> Cookies 拷贝 `xq_a_token`：

  ```bash
  export XQ_TOKEN=<拷贝的值>
  .venv/bin/python fetch_data.py --db ../data/market.db --fetch-stock-info --limit 10
  ```

  未配置时脚本照常运行，但会在首次雪球失败时提示一次；token 过期后重新
  拷贝即可。

## 请求次数

周/月 K 本就由日 K 本地重采样得到，因此 **每个 (证券, 复权档) 只请求一次
日 K**，与 `--freq` 里写了几个频率无关。全市场 5000+ 只 × 2 档复权下，
`--freq daily,weekly,monthly` 的请求数从约 3 万次降到约 1 万次。

## 退市标记

`--update-stock-list` / `--update-etf-list` 会把库内 `status='1'` 但不在
最新列表里的证券标记为 `status='0'` 并回填 `outDate`——上游列表只含在交易
证券，缺席即已摘牌。增量 K 线抓取跳过这些证券，不再白耗请求。

> 保护：新列表数量不足库内在市数量一半时判定为响应残缺，跳过本次退市
> 标记，避免一次截断的响应把全市场打成退市。

## 增量门控规则

- **daily**：仅工作日
- **weekly**：周末且最后周 K 距今 >2 天，或距今 >7 天（补漏）
- **monthly**：月初前 3 天，或距今 >31 天（补漏）

> 前复权（`--adjust 2`）在增量模式下始终从 `--start` 全量重刷：qfq 序列在
> 除权除息后整段平移，只重拉末几天会混用新旧复权基准（拼接处假跳空）。
> 不复权（`--adjust 3`）增量安全。
> 抓取时窗口会向前多取一段以补全窗口首行的 `preclose`/`pctChg` 上下文；
> 若仍缺失，入库层用 `COALESCE` 保留库中已有值，不会静默打成 NULL。
> 周/月重采样入库前会清理本轮覆盖周期内的陈旧"进行中周期"残留行，
> 同一周期不会出现多根 K。

## 断点续传

全量模式要求日/周/月三档全部成功才把该证券的 `last_fetch_date` 标记为
今天；重跑同一命令会跳过已标记的证券。`--force` 忽略标记。

## info 补齐的重试上限

`--fetch-stock-info` / `--fetch-etf-info` 的选取条件是"目标字段为空"，
而雪球对部分标的本就不返回全称 / 52 周高低——这类证券每轮都会被重扫。
未补到目标字段（含请求失败）时在 `info_backfill_attempts` 表累计次数，
达到 5 次后不再重试；补齐成功则计数清零，`--force` 可忽略上限重试。

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
