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
    "llmAnalysis": { "type": "string", "description": "详细分析文字（Markdown）" }
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
| 实际使用的 5 维得分 | `dims`（JSON） |
| 本次生效的 LLM 模型 | `model`（降级时为 NULL） |
| 提示词模板版本（SHA-1 前 8 位） | `prompt_version`（降级时为 NULL） |
| `reason` | `note`（追加到技术指标摘要末尾） |
| `llmAnalysis` | `llm_analysis`（缺失时用 `reason` 兜底） |

> 分析表 `date` 取**数据最后交易日**（最后一行日 K 的日期），不使用服务器当前日期，避免 UTC 时区跨日问题；"分析日期"≠"触发日期"。

### 基础信息来源（历史说明）

> **变更（issue #32）**：基础信息表中原需 LLM 补齐的字段（股票
> `industry / last_amount / pb / full_name / total_market_cap / high_52w / low_52w`；
> ETF `category / manager / fund_scale`）现已全部由 Akshare 数据源直接提供，
> 由 `scripts/fetch_data.py` 采集写入（见 [akshare-api.md](akshare-api.md)）。
> LLM 补齐脚本 `scripts/llm_backfill.py` 已删除，`llm_backfill_at` 列已从
> schema 移除。分析接口仍只负责打分。

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
- 启动时合并：DB 有值则用 DB，否则用默认文件；合并结果带进程内缓存（`update` 时失效），避免每次分析查库。

### 环境变量覆盖（优先级最高）

| 变量 | 说明 |
|------|------|
| `LLM_API_KEY` | API key；未设置时**跳过 LLM**，直接降级到纯技术面评分 |
| `LLM_BASE_URL` | 端点地址，默认 `https://api.openai.com/v1` |
| `LLM_MODEL` | 模型名，**优先于** `analysis_config.model` / 默认文件的 `model` |

> 分析表落库的 `model` 列记录本次实际生效的模型（含 env 覆盖后的结果）；`prompt_version` 为提示词模板内容的 SHA-1 前 8 位，模板一变版本即变。

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
1. 读取配置（DB 优先，否则默认文件，进程内缓存）
2. 从 SQLite 组装 basicInfo / klineSummary / technicalIndicators
3. 用 {{...}} 占位符渲染 promptTemplate
4. 调用 LLM（response_format=json_object），校验 JSON 输出（5 维得分 0~100，非法整次丢弃）
5. 解析失败/端点错误则重试（最多 maxRetries 次，指数退避；4xx 非 429 不重试）
6. 系统按固定权重合成综合分并换算评级/信号/持有天数（口径统一）；reason 追加进 note
7. 回填 stock_analysis / etf_analysis（字段映射见 §2，分析日期=数据最后交易日，含 dims/model/prompt_version）
8. LLM 不可用/重试耗尽时降级到纯技术面评分（估值给中性 50），任务仍为 done
```

## 6. 失败与容错

- **JSON 解析失败 / schema 不合法**：重试；仍失败则降级到纯技术面评分，不写入脏数据。
- **维度得分非法**：任一维度得分非 0~100 数值则丢弃该次结果，触发重试。
- **超时**：按 `timeoutMs` 超时，触发重试。
- **HTTP 4xx（除 429）**：不可重试，直接放弃并降级（避免空耗重试）。
- **429 / 5xx / 网络错误**：重试（最多 `maxRetries` 次），指数退避（429 起步 500ms，其余 200ms，封顶 2s）。
- **LLM 不可用（无 API key）或重试耗尽**：降级到纯技术面评分，任务正常完成（`model` / `prompt_version` 为 NULL），前端无需特判重试。
- **错误记录**：任务失败原因写入 `analysis_jobs.error` 持久化，可查询；不再只有日志。

### 6.1 任务调度与并发

- **任务落库**：每次分析在 `analysis_jobs` 表落一条记录（`kind` / `code` / `status` / `result` / `error` / 时间戳），进程重启后前端仍可查询；重启时中断的 `pending` / `running` 任务被标记为 `failed`（`interrupted by server restart`）。
- **per-code 去重**：同一标的有进行中任务时，重复触发直接复用原 job，避免重复消耗 LLM 与同一天 UPSERT 互相覆盖。
- **并发上限**：全局信号量限制同时执行的分析任务数（默认 3），超出进入 FIFO 队列。
- **GET /api/jobs/:jobId**：未知 id 返回 404（而不是伪造 `failed`），前端提示"任务不存在或已失效"。
