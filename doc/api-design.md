# 后端 API 设计

本文档只描述**后端（Nest.js）对外提供的 REST API**，不含前端调用细节（前端见 [frontend/pages.md](frontend/pages.md)）。

## 1. 通用约定

- **Base URL**：`/api`，如 `GET /api/stats`
- **数据格式**：请求/响应均为 JSON
- **时间格式**：`YYYY-MM-DD`
- **证券代码**：6 位纯数字，如 `600000`、`510050`
- **分页**：`page`（从 1 起）+ `pageSize`（默认 20，最大 100），响应带总数
- **错误**：统一 `{ statusCode, message, error }` 结构，遵循 Nest.js 默认异常格式
- **MVP0 无鉴权**：本地工具型应用，后续如需登录再引入
- **字段命名**：API 响应统一使用 **camelCase**（如 `lastTradeDate`、`isWorthBuying`），数据库列名使用 snake_case（如 `last_trade_date`），由后端 Service/Repository 层负责转换
- **字段来源约定**：
  - 基础行情字段（收盘价、涨跌幅、PE、ETF 的 `nav` 等）由采集脚本从 Akshare 写入
  - `industry` / `lastAmount`（成交额）/ `pb` / `totalMarketCap` / `fullName` / `high52w` / `low52w`（股票）及 `category` / `manager` / `fundScale`（ETF）等由采集脚本从 Akshare 直抓（个股字段需 `--fetch-stock-info` 补齐），未抓取前为 `null`
  - `rating`（买入评级）由 `score`（综合评分 0~100）换算得出，不单独入库，详见 [db-design.md](db-design.md) §6

## 2. 首页统计

### 2.1 `GET /api/stats`

返回首页四类统计指标。

**响应**

```json
{
  "stockCnt": 5120,
  "etfCnt": 1419,
  "analyzedCnt": 320,
  "stockAnalyzedCnt": 260,
  "etfAnalyzedCnt": 60,
  "analyzedTimes": 860,
  "lastTradeDate": "2026-08-13"
}
```

字段对应 issue：股票数量 / ETF 数量 / 已分析数量（合计与分品种）/ 已分析次数 / 全库最新交易日。

> **覆盖率**：设计图首页展示的"分析覆盖率百分比"（如 90.3%）由前端计算：`股票覆盖率 = stockAnalyzedCnt / stockCnt`、`ETF 覆盖率 = etfAnalyzedCnt / etfCnt`。`analyzedCnt` 是两者之和，只用于总量展示，不能用来算单个品种的占比。

> **实现说明**：后端读取数据库实时统计（见 [db-design.md](db-design.md) §8 首页统计 SQL），并将结果**缓存**（如内存缓存 + 定时失效，例如每 10 分钟刷新），避免每次请求都全表 COUNT。缓存命中时直接返回，数据变动后按失效策略刷新。

## 3. 股票 / ETF 列表

列表接口结构对称，以股票为例。支持**关键字查询、字段过滤、排序（含评级）**、分页。

### 3.1 `GET /api/stocks`

**Query 参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| `keyword` | string | 代码或名称模糊匹配 |
| `industry` | string | 行业过滤（可选） |
| `market` | string | 市场过滤：`SH` / `SZ` |
| `status` | string | 上市状态过滤（可选），对应 info 表的 `status` 列 |
| `analysisStatus` | string | 分析状态过滤：`analyzed` / `pending`。在 SQL 层过滤，`total` 与结果一致 |
| `sortBy` | string | 排序字段，见下 |
| `order` | string | `asc` / `desc`，默认 `desc` |
| `page` | number | 页码，默认 1 |
| `pageSize` | number | 每页条数，默认 20 |

**排序字段（`sortBy`）**

- `code` / `codeName`：代码 / 名称
- `lastClose`：最新收盘价
- `lastPctChg`：最新涨跌幅
- `lastAmount`：最新成交额（由 LLM 填充）
- `industry`：行业（由 LLM 填充）
- `peTtm`：市盈率
- `pb`：市净率（由 LLM 填充）
- `rating`：**最新买入评级**（按评级档位排序，`rating` 由 `score` 换算）
- `score`：最新综合评分

> 评级排序基于每只股票**最新一条**分析记录的 `score` 换算所得 `rating`（见 [db-design.md](db-design.md) §6）。

**响应**

```json
{
  "items": [
    {
      "code": "600000",
      "codeName": "浦发银行",
      "market": "SH",
      "industry": "货币金融服务",
      "fullName": "上海浦东发展银行股份有限公司",
      "lastTradeDate": "2024-01-05",
      "lastClose": 6.62,
      "lastPctChg": -0.30,
      "lastAmount": 180000000,
      "peTtm": 5.2,
      "pb": 0.6,
      "totalMarketCap": 2600000000000,
      "high52w": 8.5,
      "low52w": 5.8,
      "analysis": {
        "date": "2024-01-06",
        "rating": "A+",
        "score": 72,
        "signal": "BUY"
      }
    }
  ],
  "total": 5120,
  "page": 1,
  "pageSize": 20
}
```

> `analysis` 为最新一条分析结果的摘要；未分析过则为 `null`。
> 其中 `industry` / `lastAmount` / `pb` / `fullName` / `totalMarketCap` / `high52w` / `low52w` 由独立 LLM 补齐脚本填充，未填充前为 `null`。

### 3.2 `GET /api/etfs`

与股票列表同构，但为 ETF：

**Query 参数**：`keyword`、`category`（类别：宽基/行业/主题/策略/跨境/债券）、`manager`（管理人）、`market`、`sortBy`、`order`、`page`、`pageSize`

**排序字段（`sortBy`）**：`code` / `codeName` / `nav`（最新净值，即最后交易日收盘价）/ `lastPctChg` / `fundScale`（规模）/ `rating` / `score`

**响应 items 元素**：

```json
{
  "items": [
    {
      "code": "510050",
      "codeName": "沪深300ETF",
      "market": "SH",
      "category": "宽基",
      "manager": "华泰柏瑞",
      "lastTradeDate": "2024-01-05",
      "nav": 4.182,
      "lastPctChg": 0.04,
      "fundScale": 183200000000,
      "analysis": {
        "date": "2024-01-06",
        "rating": "B+",
        "score": 45,
        "signal": "HOLD"
      }
    }
  ],
  "total": 512,
  "page": 1,
  "pageSize": 20
}
```

> `nav`（净值）= 最后交易日收盘价 `last_close`。`category` / `manager` / `fundScale` 由独立 LLM 补齐脚本填充，未填充前为 `null`。

## 4. 详情页

### 4.1 `GET /api/stocks/:code`

返回股票基础信息 + 最近行情。

**路径参数**：`code`（如 `600000`）

**响应**

```json
{
  "code": "600000",
  "codeName": "浦发银行",
  "fullName": "上海浦东发展银行股份有限公司",
  "market": "SH",
  "type": "1",
  "ipoDate": "1999-11-10",
  "outDate": null,
  "status": "1",
  "industry": "货币金融服务",
  "lastTradeDate": "2024-01-05",
  "lastClose": 6.62,
  "lastPctChg": -0.30,
  "lastAmount": 180000000,
  "peTtm": 5.2,
  "pb": 0.6,
  "totalMarketCap": 2600000000000,
  "high52w": 8.5,
  "low52w": 5.8
}
```

不存在返回 `404`。

> `fullName` / `industry` / `lastAmount` / `pb` / `totalMarketCap` / `high52w` / `low52w` 由独立 LLM 补齐脚本填充，未填充前为 `null`。

### 4.2 `GET /api/etfs/:code`

与股票详情同构，返回 ETF 基础信息：

```json
{
  "code": "510050",
  "codeName": "沪深300ETF",
  "market": "SH",
  "type": "5",
  "ipoDate": "...",
  "outDate": null,
  "status": "1",
  "category": "宽基",
  "manager": "华泰柏瑞",
  "lastTradeDate": "...",
  "nav": 4.182,
  "lastPctChg": 0.04,
  "fundScale": 183200000000.0
}
```

> `nav` = 最后交易日收盘价 `last_close`。`category` / `manager` / `fundScale` 由独立 LLM 补齐脚本填充，未填充前为 `null`。

## 5. 分析相关

### 5.1 `GET /api/stocks/:code/analysis`

返回某只股票的分析历史（按时间倒序，可分页）。

**Query 参数**：`page`、`pageSize`

**响应**

```json
{
  "items": [
    {
      "date": "2024-01-06",
      "score": 72,
      "signal": "BUY",
      "rating": "A+",
      "isWorthBuying": 1,
      "holdDays": 15,
      "trend": "多头",
      "momentum20": 8.5,
      "volatility20": 18.2,
      "volumeRatio": 1.6,
      "note": "均线多头排列，量能温和",
      "llmAnalysis": "趋势向好，建议短线持有…"
    }
  ],
  "total": 5,
  "page": 1,
  "pageSize": 20
}
```

> 最近一次分析用于详情页展示"最后一次分析结果"。

### 5.2 `GET /api/etfs/:code/analysis`

与股票同构。

### 5.3 `POST /api/stocks/:code/analyze`

触发对单只股票的分析（调用 LLM）。**异步接口**：立即返回 `accepted`，分析完成后可轮询详情/分析接口获取结果。

**响应**

```json
{ "accepted": true, "jobId": "9f1c2b3e-..." }
```

同 `POST /api/etfs/:code/analyze`。

### 5.4 `GET /api/jobs/:jobId`

查询分析任务状态（供轮询）。任务记录持久化到 `analysis_jobs` 表，进程重启后仍可查询（重启时中断的 `pending` / `running` 任务标记为 `failed`）。

**响应**

```json
{ "jobId": "9f1c2b3e-...", "status": "running", "result": null }
```

`status` 取值：`pending` / `running` / `done` / `failed`。

**错误**

- `404`：任务 id 不存在（不再伪造 `status: "failed"`），前端提示"任务不存在或已失效"。

> 调度说明：同一标的进行中（`pending` / `running`）任务去重，重复触发复用原 job；全局并发上限 3（信号量 FIFO 排队）。

## 6. K 线数据

### 6.1 `GET /api/stocks/:code/kline`

返回某只股票 K 线（用于详情页图表）。

**Query 参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| `frequency` | string | `daily`(默认) / `weekly` / `monthly` |
| `adjust` | string | `qfq`(前复权，默认) / `raw`(不复权)。对应 db-design 的 `adjustflag`：`qfq`↔`'2'`、`raw`↔`'3'` |
| `limit` | number | 返回条数，默认 250 |
| `start` / `end` | string | 日期区间（可选） |

**响应**

```json
{
  "items": [
    { "date": "2024-01-02", "open": 6.63, "high": 6.65, "low": 6.60, "close": 6.60, "volume": 22066700, "amount": 0 }
  ]
}
```

同 `GET /api/etfs/:code/kline`。

## 7. 配置接口（LLM 提示词）

### 7.1 `GET /api/config/analysis`

返回当前分析配置（含提示词模板），供管理端查看。

**响应**

```json
{
  "model": "gpt-4o",
  "promptTemplate": "你是股票分析师…{{code}}…",
  "timeoutMs": 60000,
  "updatedAt": "2024-01-01T00:00:00Z"
}
```

### 7.2 `PUT /api/config/analysis`

更新分析配置（含提示词模板），后续迭代直接改配置不改代码。

**请求体**：同上方响应结构，可部分更新。

```json
{ "promptTemplate": "新的模板…" }
```

**响应**：返回更新后的完整配置。
