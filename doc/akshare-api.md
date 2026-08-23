# Akshare 接口清单（本项目实际使用）

> 迁移自 BaoStock（2026-08-22，issue #32）。以下接口均经实测验证可用。

## 1. 数据源接口

| 用途 | 接口 | 源站点 | 调用方式 | 备注 |
|------|------|--------|----------|------|
| A 股列表 + 实时行情 | `stock_zh_a_spot_tx` | 腾讯 | 一次拉全市场（~12s） | 字段：`code`（`sh600519` 式）、`name`、`pe_ttm`、`zsz`（总市值，亿）、`zxj`（现价）、`zdf`（涨跌幅）、`turnover`（成交额，万）；入库统一换算为元 |
| 股票日 K | `stock_zh_a_daily` | 新浪 | 逐只 | `adjust`：`""` 不复权 / `"qfq"` 前复权 / `"hfq"` 后复权；含换手率列 `turnover` |
| 股票周/月 K | —（本地重采样） | — | — | 数据源无直抓接口，由日 K 聚合：open 首值 / close 尾值 / high max / low min / volume+amount 求和 |
| 个股基本信息 | `stock_individual_basic_info_xq` | 雪球 | 逐只（`SH600000` 式） | `org_name_cn` 全称、`affiliate_industry.ind_name` 行业、`listed_date` 上市日期（毫秒时间戳） |
| 个股实时估值 | `stock_individual_spot_xq` | 雪球 | 逐只 | `市净率`、`52周最高`、`52周最低`、`资产净值/总市值`（元）；ETF 同样适用（雪球把 ETF 当 quote），`--fetch-etf-info` 复用本接口补齐 `high_52w`/`low_52w` |
| ETF 列表 | `fund_etf_category_sina`（参数 `"ETF基金"`） | 新浪 | 一次拉全量 | 字段：`代码`（带小写前缀如 `sh510050`，脚本剥离并用于市场判断）、`名称` |
| ETF 日 K | `fund_etf_hist_sina` | 新浪 | 逐只 | **仅不复权**；返回全量历史，脚本本地按日期过滤；含 `prevclose` |
| ETF 类别 | `fund_etf_category_ths`（参数 `"ETF基金"`） | 同花顺 | 一次拉全量 | `基金代码` → `基金类型` |
| ETF 规模/管理人 | `fund_scale_open_sina` | 新浪 | 一次拉全量 | 覆盖全部开放式基金（含 ETF），`总募集规模`（万→元）、`基金经理`、`成立日期` |

> **ETF 基金详情接口不可用**：`fund_individual_basic_info_xq` /
> `fund_individual_detail_info_xq` 走蛋卷基金
> （`danjuanfunds.com/djapi/fund/{code}`），仅覆盖蛋卷销售的场外基金，
> 对场内 ETF 返回 `该基金暂不销售`（2026-08-22 实测）；故 ETF 信息补齐
> 用雪球 quote 接口（见上表）。

## 2. 代码格式约定

| 场景 | 格式 | 示例 |
|------|------|------|
| 数据库存储 | 6 位纯数字 | `600000` |
| 新浪 K 线接口 | 小写前缀 | `sh600000` |
| 雪球接口 | 大写前缀 | `SH600000` |
| 腾讯返回 | 小写前缀 | `sh600519` |

格式转换统一在 `scripts/akshare_source.py` 内完成（`to_sina_code` /
`to_xq_code` / `strip_prefix`），上层只见 6 位纯数字。

## 3. 已知限制

1. **东财（`*_em`）系接口在当前网络环境不可用**（多次重试均
   `RemoteDisconnected`，2026-08-22 实测），本项目禁用；若网络环境变化可
   考虑切换回东财源（字段更丰富）。
2. **新浪不支持 ETF 复权**：`etf_kline_*` 仅 `adjustflag='3'`。
3. **雪球个股接口需逐只调用**（~5400 只 × 2 接口）：全量补齐预计 1-2
   小时，`--fetch-stock-info` 只处理 `full_name` 为空的增量，建议每周跑一次。
4. **`tradestatus` 恒为 `'1'`、`isST` 恒为 `'0'`**：新数据源不提供交易状态
   与 ST 标记。
5. **`etf_kline_daily` 估值列（`peTTM` 等）恒为 `NULL`**：新数据源不提供。
6. **退市证券无标记**：退市股不再出现在腾讯列表中，其旧数据行保留但不再
   更新（`status` 不改为 `'0'`）。
7. **交易所新号段**：`market_of` 号段规则可能滞后于交易所新号段（目前沪市
   ETF 段位 `51/52/53/55/56/58` 已覆盖，如 `52` 中证 A500 系）。股票列表（腾讯源返回
   带前缀代码）与 ETF 列表（新浪源带前缀）均优先用源前缀判断市场；未知号段的
   股票（如北交所 `92` 开头）跳过。

## 4. 抓取计划

| 任务 | 频率 | 命令 |
|------|------|------|
| 列表刷新 + daily 增量 | 每交易日 | `--update-stock-list` / `--update-etf-list` + `--fetch-*-kline --incremental` |
| weekly/monthly 增量 | 随 daily 跑 | 由频率门控自动决定 |
| 个股信息补齐 | 每周一次或手动 | `--fetch-stock-info [--limit N]` |
| ETF 信息补齐（52周高低） | 每周一次或手动 | `--fetch-etf-info [--limit N]` |

限速与容错：串行 + `--sleep`（默认 0.5 秒/只）+ 指数退避重试（默认 3 次，
1s/4s/16s）。接口清单如有失效，优先升级 `akshare` 版本再核对本文档。
