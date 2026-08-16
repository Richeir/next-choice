# BaoStock API 参考

`baostock` 包的公开函数全集（含签名）与各接口的真实返回值示例。API 描述独立于此文档；快速上手与项目约定见 `README.md`。

---

## 1. 完整 API 目录

以下为 `baostock` 包的公开函数全集（含签名）。按功能分类：

### 1.1 连接类

| 函数 | 签名 | 说明 |
|------|------|------|
| `login` | `login(user_id='anonymous', password='123456')` | 登录，返回含 `error_code/error_msg` 的对象 |
| `logout` | `logout(user_id='anonymous')` | 登出 |
| `set_API_key` | `set_API_key(apiKey='')` | 设置 API key |

### 1.2 行情 / K 线（核心）

| 函数 | 签名 | 说明 |
|------|------|------|
| `query_history_k_data_plus` | `(code, fields, start_date=None, end_date=None, frequency='d', adjustflag='3')` | 历史 K 线，最常用 |
| `query_adjust_factor` | `(code, start_date=None, end_date=None)` | 复权因子 |
| `query_daily_adjust_factor` | `(date=None)` | 全市场每日复权因子 |
| `query_daily_history_k_AStock` | `(date='')` | 全 A 股某日行情 |
| `query_daily_history_k_ETF` | `(date='')` | 全市场 ETF 某日日 K 线，返回全市场所有 ETF（详见 [§2.8](#28-query_daily_history_k_etf--全市场-etf-日-k-线)） |

### 1.3 证券信息

| 函数 | 签名 | 说明 |
|------|------|------|
| `query_stock_basic` | `(code='', code_name='')` | 证券基本信息（名称、上市/退市日期、类型、状态） |
| `query_all_stock` | `(day=None)` | 指定日期可交易的全部股票 |
| `query_stock_industry` | `(code='', date='')` | 股票所属行业 |

### 1.4 指数成分股

| 函数 | 签名 | 说明 |
|------|------|------|
| `query_hs300_stocks` | `(date='')` | 沪深 300 成分股 |
| `query_sz50_stocks` | `(date='')` | 上证 50 成分股 |
| `query_zz500_stocks` | `(date='')` | 中证 500 成分股 |

### 1.5 财务数据（按季度）

| 函数 | 签名 | 说明 |
|------|------|------|
| `query_profit_data` | `(code, year=None, quarter=None)` | 利润表 |
| `query_operation_data` | `(code, year=None, quarter=None)` | 营运能力 |
| `query_growth_data` | `(code, year=None, quarter=None)` | 成长能力 |
| `query_balance_data` | `(code, year=None, quarter=None)` | 资产负债 |
| `query_cash_flow_data` | `(code, year=None, quarter=None)` | 现金流 |
| `query_dupont_data` | `(code, year=None, quarter=None)` | 杜邦分析 |

### 1.6 业绩报告与分红

| 函数 | 签名 | 说明 |
|------|------|------|
| `query_forecast_report` | `(code, start_date=None, end_date=None)` | 业绩预告 |
| `query_performance_express_report` | `(code, start_date=None, end_date=None)` | 业绩快报 |
| `query_dividend_data` | `(code, year=None, yearType='report')` | 分红送配 |

### 1.7 宏观利率

| 函数 | 签名 | 说明 |
|------|------|------|
| `query_deposit_rate_data` | `(start_date='', end_date='')` | 存款利率 |
| `query_loan_rate_data` | `(start_date='', end_date='')` | 贷款利率 |
| `query_money_supply_data_month` | `(start_date='', end_date='')` | 月度货币供应量 |
| `query_money_supply_data_year` | `(start_date='', end_date='')` | 年度货币供应量 |
| `query_required_reserve_ratio_data` | `(start_date='', end_date='', yearType='0')` | 存款准备金率 |

### 1.8 交易日历

| 函数 | 签名 | 说明 |
|------|------|------|
| `query_trade_dates` | `(start_date=None, end_date=None)` | 交易日历（含是否交易日标记） |

---

## 2. 各 API 返回值详解与真实输出

`demo.py` 的真实运行输出如下（跑于一次实际登录，返回均为 `error_code='0'`）：

### 2.1 `query_history_k_data_plus` — 历史 K 线

最核心的接口。`frequency` 可取 `'d'/'w'/'m'/'5'/'15'/'30'/'60'`（日/周/月/5 分钟…），`adjustflag` 为复权方式（`'1'` 后复权、`'2'` 前复权、`'3'` 不复权）。`fields` 自由指定列。

```text
[query_history_k_data_plus 日K线]
  fields = ['date', 'code', 'open', 'high', 'low', 'close', 'volume']
  rows   = 4
    ['2024-01-02', 'sh.600000', '6.6300', '6.6500', '6.6000', '6.6000', '22066700']
    ['2024-01-03', 'sh.600000', '6.5900', '6.6500', '6.5900', '6.6400', '18203654']
    ['2024-01-04', 'sh.600000', '6.6400', '6.6700', '6.5500', '6.6200', '28885978']
```

### 2.2 `query_stock_basic` — 证券基本信息

```text
[query_stock_basic 证券基本信息]
  fields = ['code', 'code_name', 'ipoDate', 'outDate', 'type', 'status']
  rows   = 1
    ['sh.600000', '浦发银行', '1999-11-10', '', '1', '1']
```

字段：`type` 股票类型、`status` 上市状态。浦发银行退市日期 `outDate` 为空（在上市）。

### 2.3 `query_hs300_stocks` — 沪深 300 成分股

```text
[query_hs300_stocks 沪深300成分]
  fields = ['updateDate', 'code', 'code_name']
  rows   = 300
    ['2024-01-01', 'sh.600000', '浦发银行']
    ['2024-01-01', 'sh.600009', '上海机场']
    ['2024-01-01', 'sh.600010', '包钢股份']
```

### 2.4 `query_profit_data` — 季度利润表

财务类接口都要传 `year` + `quarter`（1~4）。`netProfit` 为净利润，`epsTTM` 为滚动每股收益等。

```text
[query_profit_data 季度利润表]
  fields = ['code', 'pubDate', 'statDate', 'roeAvg', 'npMargin', 'gpMargin',
            'netProfit', 'epsTTM', 'MBRevenue', 'totalShare', 'liqaShare']
  rows   = 1
    ['sh.600000', '2024-04-30', '2023-12-31', '0.051598', '0.215811', '',
     '37429000000.000000', '1.250401', '329633000000.000000', '29352176848.00', '29352176848.00']
```

### 2.5 `query_forecast_report` — 业绩预告

**返回 0 行**也是一种真实结果（该股票在该区间无业绩预告记录），`error_code` 仍为 `'0'`，因此**判断成功与否要看 `error_code`，不要只看行数**：

```text
[query_forecast_report 业绩预告]
  fields = ['code', 'profitForcastExpPubDate', 'profitForcastExpStatDate',
            'profitForcastType', 'profitForcastAbstract',
            'profitForcastChgPctUp', 'profitForcastChgPctDwn']
  rows   = 0
```

### 2.6 `query_deposit_rate_data` — 存款利率（宏观）

```text
[query_deposit_rate_data 存款利率]
  fields = ['pubDate', 'demandDepositRate', 'fixedDepositRate3Month',
            'fixedDepositRate6Month', 'fixedDepositRate1Year', 'fixedDepositRate2Year',
            'fixedDepositRate3Year', 'fixedDepositRate5Year', 'installmentFixedDepositRate1Year',
            'installmentFixedDepositRate3Year', 'installmentFixedDepositRate5Year']
  rows   = 2
    ['2015-03-01', '0.350000', '2.100000', '2.300000', '2.500000', '3.100000',
     '3.750000', '', '2.100000', '2.300000', '']
    ['2015-05-11', '0.350000', '1.850000', '2.050000', '2.250000', '2.850000',
     '3.500000', '', '1.850000', '2.050000', '']
```

### 2.7 `query_trade_dates` — 交易日历

`is_trading_day` 字段为 `'1'` 表示交易日、`'0'` 表示非交易日：

```text
[query_trade_dates 交易日历]
  fields = ['calendar_date', 'is_trading_day']
  rows   = 10
    ['2024-01-01', '0']
    ['2024-01-02', '1']
    ['2024-01-03', '1']
```

### 2.8 `query_daily_history_k_ETF` — 全市场 ETF 日 K 线

一次返回**指定日期全市场所有 ETF** 的日 K 线（不按单只代码查询，仅传日期）。返回字段较多，除常见 K 线字段外还含涨跌幅、估值指标与交易状态等。与 A 股接口不同，该接口不分页，一次拉全量（约千余行）。

```text
[query_daily_history_k_ETF 全市场ETF日K线]（2026-02-04，共 1419 行，展示前 3 行）
  fields = ['date', 'code', 'open', 'high', 'low', 'close', 'preclose',
            'volume', 'amount', 'adjustflag', 'turn', 'tradestatus',
            'pctChg', 'peTTM', 'pbMRQ', 'psTTM', 'pcfNcfTTM', 'isST']
  rows   = 1419
    ['2026-02-04', 'sh.510010', '1.8060', '1.8330', '1.8060', '1.8290', '1.8060',
     '161200', '294216.0000', '3', '0.114713', '1', '1.273500', '', '', '', '', '1']
    ['2026-02-04', 'sh.510020', '3.8580', '3.9050', '3.8180', '3.8840', '3.8510',
     '250510', '968709.0000', '3', '0.698812', '1', '0.856900', '', '', '', '', '1']
    ['2026-02-04', 'sh.510030', '1.0650', '1.0830', '1.0630', '1.0820', '1.0650',
     '6611300', '7107290.0000', '3', '3.965278', '1', '1.596200', '', '', '', '', '1']
```

字段说明：`preclose` 前收盘价、`amount` 成交额（元）、`turn` 换手率、`tradestatus` 交易状态（`'1'` 正常交易）、`pctChg` 涨跌幅（%）、`isST` 是否 ST。`peTTM/pbMRQ/psTTM/pcfNcfTTM` 等估值指标对 ETF 多为空字符串。

> 注意：该接口的返回对象**没有** `rows` 隐藏属性，取行数请用 `len(rs.data)`。ETF 数据范围：日/周/月 K 线及 5/15/30/60 分钟 K 线自 `2026-01-05` 起。
