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
```

参数说明：

| 参数 | 必填 | 默认 | 说明 |
|------|------|------|------|
| `--db` | 否 | `../data/market.db` | SQLite 数据库路径 |
| `--codes` | 是 | — | 逗号分隔证券代码，如 `sh.600000,sz.159915` |
| `--freq` | 否 | `daily` | 逗号分隔频率：`daily,weekly,monthly` |
| `--adjust` | 否 | `3` | 逗号分隔复权：`2`(前复权) / `3`(不复权) |
| `--start` | 否 | — | 起始日期 `YYYY-MM-DD` |
| `--end` | 否 | — | 结束日期 `YYYY-MM-DD` |

> 注意：ETF 的 K 线数据范围自 **2026-01-05** 起；股票自 1990-12-19 起。
> 复权因子表 `adjust_factor` 当前由脚本按需写入（可扩展 `--factors`）。

## 流程

1. `login()` 登录
2. 逐个 code 用 `query_stock_basic` 写 `stock_info`（type='1'）/ `etf_info`（type='5'）
3. 逐个 (code, freq, adjustflag) 用 `query_history_k_data_plus` 幂等写 K 线
   （`INSERT OR REPLACE`，主键 `UNIQUE(code, date, adjustflag)`）
4. 用不复权日 K 回填 `last_trade_date / last_close / last_pct_chg`
5. `logout()` 登出

## 测试

```bash
source .venv/bin/activate

# 仅单元测试（不打网络，快）
python -m pytest tests -q -m "not e2e"

# 全部（含 E2E，真实连接 BaoStock，拉少量数据）
python -m pytest tests -q
```

- `tests/test_transform.py`：数据转换 / 市场推断 / 表名映射
- `tests/test_db.py`：建表（11 张）、幂等写入、行情回填（临时库）
- `tests/test_e2e.py`：真实 BaoStock 拉取小样本入库 + 回填的端到端验证
