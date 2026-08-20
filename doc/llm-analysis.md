# LLM 分析设计

本文档描述 MVP0 的 LLM 分析模块：提示词模板、输出 JSON schema、全局配置化设计。

## 1. 设计目标

- 单个大模型对个股 / ETF 做**多维度评分**，由系统合成综合分并换算评级/信号/持有天数。
- 输出需**结构化**（JSON），回填 `stock_analysis / etf_analysis` 与分析文字。
- 提示词模板**全局可配置**（后续迭代可改模板，不改代码），通过配置接口管理。
- **口径统一**：LLM 只输出各维度得分（不直接给评级），综合分与评级由系统按固定权重换算，避免 LLM 评级与系统评分打架。

## 2. 输出 JSON Schema

LLM 的回复必须是严格 JSON，**必填** 5 个维度得分（均 0~100，越高越有利）+ `reason`：

```json
{
  "type": "object",
  "required": ["trend", "momentum", "valuation", "volume", "stability", "reason"],
  "properties": {
    "trend": { "type": "number", "minimum": 0, "maximum": 100, "description": "趋势强度" },
    "momentum": { "type": "number", "minimum": 0, "maximum": 100, "description": "动量" },
    "valuation": { "type": "number", "minimum": 0, "maximum": 100, "description": "估值吸引力" },
    "volume": { "type": "number", "minimum": 0, "maximum": 100, "description": "量能" },
    "stability": { "type": "number", "minimum": 0, "maximum": 100, "description": "风险（波动低得分高）" },
    "reason": { "type": "string", "description": "判断依据，自然语言摘要" },
    "llmAnalysis": { "type": "string", "description": "详细分析文字（Markdown）" },
    "industry": { "type": "string", "description": "所属行业（股票）" },
    "lastAmount": { "type": "number", "description": "成交额（股票）" },
    "pb": { "type": "number", "description": "市净率（股票）" },
    "fullName": { "type": "string", "description": "公司全称（股票）" },
    "totalMarketCap": { "type": "number", "description": "总市值（股票）" },
    "high52w": { "type": "number", "description": "52 周最高价（股票）" },
    "low52w": { "type": "number", "description": "52 周最低价（股票）" },
    "category": { "type": "string", "description": "ETF 类别（ETF）" },
    "manager": { "type": "string", "description": "管理人（ETF）" },
    "fundScale": { "type": "number", "description": "基金规模（ETF）" }
  }
}
```

### 综合评分与评级（系统换算）

LLM 的 5 个维度得分由系统加权合成（权重见 `backend/src/common/scoring.ts`）：

```text
score = 0.25×trend + 0.20×momentum + 0.20×valuation + 0.15×volume + 0.20×stability
```

- `score` → `rating`：`ratingFromScore`（9 档）
- `score` + 趋势 → `signal`：`signalFromScore`（BUY / HOLD / SELL）
- `signal` → `is_worth_buying`；`score` → `hold_days`（`holdDaysFromTrend`）

> LLM 不输出评级/信号/持有天数，这些全部由系统计算，保证 `score` 与 `rating` 口径一致。
>
> **信号方向以技术面均线为准**：`signalFromScore` 的 BUY 门槛（`score>=65 且多头`）与 `holdDaysFromTrend` 使用的趋势方向均取自技术面均线排列（`technical.trend`），而非 LLM 的趋势得分。LLM 的 `trend` 维度分只影响加权合成后的 `score`，不直接决定 BUY/HOLD/SELL 方向——信号应基于客观、可复现的技术面数据判定，LLM 打分仅作权重加成。若 LLM 趋势维度给高分但技术面为空头，`score` 可能 ≥65 但仍保持 HOLD/SELL。

### 字段回填映射

| 来源 | 分析表列 |
|-----------|----------|
| 5 维得分合成 `score` | `score` |
| `score` 换算 | `rating`（9 档）/ `signal` |
| `score` 换算 | `hold_days` |
| `signal` 换算 | `is_worth_buying` |
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
对标的进行多维度评分（只输出维度得分，不做最终评级，评级由系统换算）。

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
每个维度得分是 0~100 的整数，分值越高越有利。字段必须满足以下 schema：
- trend：趋势强度得分，价格与均线多头结构越清晰越高
- momentum：动量得分，近 20 日涨跌动能越强越高（追高需谨慎下调）
- valuation：估值吸引力得分，估值越低/越合理越高；ETF 无 PE/PB 时按指数相对位置中性判断
- volume：量能得分，量价配合与资金关注度越好越高
- stability：风险得分，波动率越低越稳定越高
- reason：一句话的判断摘要
- llmAnalysis：详细分析文字，可用 Markdown，说明趋势、估值、量能、风险与买卖建议
可选回填字段（提供可帮助丰富展示）：industry / lastAmount / pb / fullName / totalMarketCap / high52w / low52w / category / manager / fundScale

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
- **维度得分非法**：任一维度得分非 0~100 数值则丢弃该次结果，视为失败。
- **超时**：按 `timeoutMs` 超时，触发重试。
- **LLM 不可用**：任务 `failed`，前端提示可重试；MVP0 不做降级到纯技术面评分。
