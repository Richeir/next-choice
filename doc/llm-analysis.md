# LLM 分析设计

本文档描述 MVP0 的 LLM 分析模块：提示词模板、输出 JSON schema、全局配置化设计。

## 1. 设计目标

- 单个大模型判断个股 / ETF 是否值得买入，并给出大致持有天数预测。
- 输出需**结构化**（JSON），回填 `rating / is_worth_buying / hold_days` 与分析文字。
- 提示词模板**全局可配置**（后续迭代可改模板，不改代码），通过配置接口管理。

## 2. 输出 JSON Schema

LLM 的回复必须是严格 JSON，schema 如下（`rating` 取值限定 9 档）：

```json
{
  "type": "object",
  "required": ["rating", "isWorthBuying", "holdDays", "reason"],
  "properties": {
    "rating": {
      "type": "string",
      "enum": ["S+", "S", "A+", "A", "B+", "B", "C+", "C", "D"]
    },
    "isWorthBuying": { "type": "boolean" },
    "holdDays": { "type": "integer", "minimum": 0, "maximum": 365 },
    "reason": { "type": "string", "description": "判断依据，自然语言摘要" },
    "llmAnalysis": {
      "type": "string",
      "description": "详细分析文字（Markdown），保存到分析表的 llm_analysis 列"
    },
    "industry": { "type": "string", "description": "所属行业（股票）" },
    "lastAmount": { "type": "number", "description": "成交额，单位元（股票）" },
    "pb": { "type": "number", "description": "市净率（股票）" },
    "fullName": { "type": "string", "description": "公司全称（股票）" },
    "totalMarketCap": { "type": "number", "description": "总市值，单位元（股票）" },
    "high52w": { "type": "number", "description": "52 周最高价（股票）" },
    "low52w": { "type": "number", "description": "52 周最低价（股票）" },
    "category": { "type": "string", "description": "ETF 类别（ETF）" },
    "manager": { "type": "string", "description": "管理人（ETF）" },
    "fundScale": { "type": "number", "description": "基金规模（ETF）" }
  }
}
```

### 字段回填映射

| JSON 字段 | 分析表列 |
|-----------|----------|
| `rating` | `rating`（9 档） |
| `isWorthBuying` | `is_worth_buying`（true→1，false→0） |
| `holdDays` | `hold_days` |
| `reason` | `note`（评分理由摘要） |
| `llmAnalysis` | `llm_analysis` |

### 额外回填（info 表，供列表/详情展示）

除分析表外，LLM 在分析时**同时回填**基础信息表，用于列表页展示与排序（BaoStock 无法直接获取这些字段）：

| JSON 字段 | 目标列 | 适用标的 |
|-----------|--------|----------|
| `industry` | `stock_info.industry` | 股票 |
| `lastAmount` | `stock_info.last_amount`（成交额） | 股票 |
| `pb` | `stock_info.pb`（市净率） | 股票 |
| `fullName` | `stock_info.full_name`（公司全称） | 股票 |
| `totalMarketCap` | `stock_info.total_market_cap`（总市值） | 股票 |
| `high52w` / `low52w` | `stock_info.high_52w` / `stock_info.low_52w` | 股票 |
| `category` | `etf_info.category`（类别） | ETF |
| `manager` | `etf_info.manager`（管理人） | ETF |
| `fundScale` | `etf_info.fund_scale`（规模） | ETF |

这些字段为**可空**，未分析（未填充）前为 `NULL`。

## 3. 提示词模板

模板采用占位符注入变量，运行时由后端填充后调用 LLM。

### 3.1 默认模板

```text
你是一位资深 A 股分析师。请基于以下证券信息与历史 K 线数据，
判断该标的当前是否值得买入，并给出大致持有天数预测。

## 标的类型
{{securityType}}（股票 / ETF）

## 证券基础信息
{{basicInfo}}

## 历史 K 线摘要
{{klineSummary}}

## 最近 20 日技术指标
{{technicalIndicators}}

## 输出要求
请严格输出一个 JSON 对象，不要包含任何多余文字或 Markdown 代码块。
JSON 字段必须满足以下 schema：
- rating：9 档评级之一：S+, S, A+, A, B+, B, C+, C, D
- isWorthBuying：布尔值，是否值得买入
- holdDays：整数，建议持有天数（0 表示不建议买入持有，范围 0~365）
- reason：一句话的买入判断摘要
- llmAnalysis：详细分析文字，可用 Markdown，说明趋势、量能、风险与买卖建议

直接输出 JSON 即可。
```

### 3.2 模板变量（运行时注入）

| 变量 | 来源 |
|------|------|
| `{{securityType}}` | 标的类型（股票/ETF） |
| `{{basicInfo}}` | `stock_info` / `etf_info` 基础字段 |
| `{{klineSummary}}` | 最近 N 日 K 线摘要（可裁剪，控制 token） |
| `{{technicalIndicators}}` | 均线/动量/波动/量比等指标 |

> `{{klineSummary}}` 与 `{{technicalIndicators}}` 内容较多，可配置截断条数与精简格式，控制 token 消耗。

## 4. 全局配置设计

提示词模板与分析参数**不硬编码在代码中**，集中存放于配置，便于后续迭代。两种存储方案，推荐 A。

### 方案 A（推荐）：配置文件 + 可选 DB 覆盖

- **默认值**：存放于后端 `config/analysis.config.json`（含 `model`、`promptTemplate`、`timeoutMs` 等）。
- **运行时覆盖**：通过 `PUT /api/config/analysis` 修改，写入数据库 `analysis_config` 表，优先于默认文件。
- 启动时合并：DB 有值则用 DB，否则用默认文件。

**`analysis_config` 表结构**（若采用 DB 覆盖）

```sql
CREATE TABLE IF NOT EXISTS analysis_config (
    key            TEXT PRIMARY KEY,
    value          TEXT,      -- JSON 字符串
    updated_at     TEXT
);
```

存储示例：

| key | value |
|-----|-------|
| `model` | `"gpt-4o"` |
| `promptTemplate` | `"你是一位资深 A 股分析师…"` |
| `timeoutMs` | `60000` |
| `klineLimit` | `120` |

### 方案 B（简化）：仅配置文件

只使用 `config/analysis.config.json`，改模板需重启服务。MVP0 够用，但迭代体验略差。

> **建议 MVP0 采用方案 A**，一次到位，后续迭代只改配置不改代码。

### 配置项清单

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `model` | string | `gpt-4o` | LLM 模型名 |
| `promptTemplate` | string | 见 §3.1 | 提示词模板 |
| `timeoutMs` | number | `60000` | LLM 调用超时 |
| `maxRetries` | number | `2` | 失败重试次数 |
| `klineLimit` | number | `120` | 注入模板的 K 线条数 |
| `temperature` | number | `0.2` | 采样温度 |

## 5. 调用流程

```
1. 读取配置（DB 优先，否则默认文件）
2. 从 SQLite 组装 basicInfo / klineSummary / technicalIndicators
3. 用 {{...}} 占位符渲染 promptTemplate
4. 调用 LLM，校验 JSON 输出（含 rating 枚举校验）
5. 解析失败则重试（最多 maxRetries 次）
6. 回填 stock_analysis / etf_analysis（字段映射见 §2）
7. 失败时记录错误，任务状态置 failed
```

## 6. 失败与容错

- **JSON 解析失败 / schema 不合法**：重试；仍失败则任务 `failed`，不写入脏数据。
- **评级越界**：`rating` 不在枚举内则丢弃该次结果，视为失败。
- **超时**：按 `timeoutMs` 超时，触发重试。
- **LLM 不可用**：任务 `failed`，前端提示可重试；MVP0 不做降级到纯技术面评分。
