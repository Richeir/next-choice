# next-choice

> 股票分析 Demo（M·STOCK）：用 Akshare 拉取行情 → SQLite 落地 → Nest.js REST → React 前端展示，并接入 LLM 给出买入判断与持有天数。

## 项目简介

`next-choice` 是一个本地化、轻量级的股票 / ETF 数据与分析 Demo，覆盖完整的数据链路：

- **采集**：独立 Python 脚本基于 [Akshare](https://akshare.akfamily.xyz/)（腾讯/新浪/雪球/同花顺源）拉取证券基础信息和日/周/月 K 线，幂等写入本地 SQLite。
- **存储**：SQLite 单库（默认 `data/market.db`），schema 在 `backend/database/schema.sql` 单一来源，被 Python 脚本与 Nest.js 后端共用。
- **后端**：Nest.js 10 + better-sqlite3，提供 REST API（列表/详情/K 线/统计/分析任务/配置）。
- **前端**：React 18 + Vite 5 + React Router 6 + ECharts，展示首页统计、列表、详情与 K 线。
- **分析**：支持“纯技术面评分”（开箱即用）和“LLM 分析”（配置 `ANALYSIS_LLM_API_KEY` 后启用）。

## 仓库结构

```
next-choice/
├── frontend/         # React + Vite + TS 前端
├── backend/          # Nest.js + TS + better-sqlite3 后端
├── scripts/          # Python 采集脚本（Akshare → SQLite）
├── backend/database/schema.sql   # SQLite schema 唯一来源
├── data/             # SQLite 数据库文件（默认 market.db，被 git 忽略）
├── doc/              # 设计文档（架构、API、DB、LLM 等）
├── AGENTS.md         # Agent 工作约定与提 PR 自动 Review 流程
└── README.md         # 本文件
```

## 技术栈

| 层 | 选型 | 版本 |
|----|------|------|
| 前端 | React / Vite / TypeScript / React Router / Axios / ECharts | React 18、Vite 5、TS 5 |
| 后端 | Nest.js / TypeScript / better-sqlite3 / class-validator | Nest 10、TS 5、better-sqlite3 13 |
| 数据库 | SQLite（文件型，默认 `data/market.db`） | 3.x |
| 采集 | Python + Akshare | Python ≥ 3.11、Akshare 1.18.x |
| LLM | OpenAI 兼容接口（可选） | SDK 4.x |

> 详细版本与选型理由见 [`doc/tech-stack.md`](doc/tech-stack.md)。

## 快速开始

### 0. 环境要求

- **Node.js** ≥ 20
- **Python** ≥ 3.11
- 推荐同时启动两个终端：一个跑后端、一个跑前端

### 1. 拉取并初始化数据库

```bash
git clone <repo-url> next-choice
cd next-choice

# 创建 venv 并安装 Akshare
python3 -m venv scripts/.venv
source scripts/.venv/bin/activate
pip install -r scripts/requirements.txt

# 拉取 ETF 基础信息（写入 etf_info 表）
python scripts/fetch_data.py --update-etf-list

# 拉取 A 股基础信息（写入 stock_info 表）
python scripts/fetch_data.py --update-stock-list

# 拉取若干股票/ETF 的 K 线（6 位纯数字代码；默认 5 年窗口，周/月由日 K 本地重采样）
python scripts/fetch_data.py \
    --db data/market.db \
    --codes 600000,510050 \
    --freq daily,weekly,monthly --adjust 2,3
```

> 参数与回溯窗口约定见 [`scripts/README.md`](scripts/README.md)。
> 默认数据落地路径：`data/market.db`（在 `.gitignore` 中，不会入库）。

### 2. 启动后端

```bash
cd backend
npm install
npm run start:dev      # 开发模式（热重载）
# 或：npm run build && npm run start:prod
```

- 默认监听 `http://localhost:3100`，全局前缀 `/api`
- 数据库路径：仓库根 `data/market.db`（可用环境变量 `DB_PATH` 覆盖）
- 端口：`PORT` 环境变量覆盖

### 3. 启动前端

```bash
cd frontend
npm install
npm run dev            # http://localhost:5173
```

前端 `vite.config.ts` 已将 `/api` 代理到 `http://localhost:3100`，保持默认即可联通后端。

## 主要接口（后端）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/api/stats` | 首页统计（内存缓存 10 分钟） |
| GET  | `/api/stocks` / `/api/etfs` | 列表（分页 / 关键字 / 过滤 / 排序 / 评级） |
| GET  | `/api/stocks/:code` / `/api/etfs/:code` | 详情（不存在返回 404） |
| GET  | `/api/stocks/:code/analysis` / `/api/etfs/:code/analysis` | 分析历史 |
| GET  | `/api/stocks/:code/kline` / `/api/etfs/:code/kline` | K 线（`frequency` / `adjust` / `limit` / `start` / `end`） |
| POST | `/api/stocks/:code/analyze` / `/api/etfs/:code/analyze` | 触发异步分析，返回 `jobId` |
| GET  | `/api/jobs/:jobId` | 查询分析任务状态 |
| GET/PUT | `/api/config/analysis` | 读写分析配置（含 LLM 提示词模板） |

详细字段约定见 [`doc/api-design.md`](doc/api-design.md)、[`doc/backend/modules.md`](doc/backend/modules.md)。

## 前端页面

| 路由 | 页面 |
|------|------|
| `/` | 首页统计卡片 |
| `/stocks` | 股票列表（筛选 / 排序 / 分页） |
| `/etfs` | ETF 列表 |
| `/stocks/:code` | 股票详情（分析卡片 + 关键指标 + K 线） |
| `/etfs/:code` | ETF 详情 |

页面与设计见 [`doc/frontend/pages.md`](doc/frontend/pages.md)。

## 分析（LLM）模式

- **默认（无 LLM key）**：仅做技术面评分（规则见 [`doc/db-design.md`](doc/db-design.md) §6），前端可直接看到买入/持有天数的输出。
- **启用 LLM**：配置环境变量 `ANALYSIS_LLM_API_KEY`（及模型/端点），提示词模板可由 `GET/PUT /api/config/analysis` 在线覆盖并落库（DB 优先于文件）。
- 调用超时与失败会写入 `llm_analysis` 失败标记，前端提示“分析失败可重试”。

## 数据库

- 唯一 schema 定义：[`backend/database/schema.sql`](backend/database/schema.sql)（共 11 张表）。
- 关键表：`stock_info` / `etf_info` / `kline_stock_daily` / `kline_etf_daily` / `kline_*_weekly` / `kline_*_monthly` / `adjust_factor` / `stock_analysis` / `etf_analysis` / `llm_analysis` / `analysis_config`。
- Python 采集脚本与 Nest.js 后端共用同一份 `schema.sql`（脚本通过 `scripts/db.py` 读取并执行）。
- K 线主键：`UNIQUE(code, date, adjustflag)`，因此可重复运行脚本而幂等覆盖。
- 详细字段与索引见 [`doc/db-design.md`](doc/db-design.md)。

## 测试

```bash
# Python：单元 + E2E（E2E 会真实连接 Akshare 数据源）
cd scripts && source .venv/bin/activate
python -m pytest tests -q -m "not e2e"   # 仅单元
python -m pytest tests -q                 # 全部

# 后端：单元 + e2e（e2e 用临时库，不污染真实数据）
cd backend
npm test
npm run test:e2e

# 前端：vitest 页面级测试（mock API）
cd ../frontend
npm test
```

## 文档索引

设计文档位于 [`doc/`](doc/README.md)，推荐阅读顺序：

1. [架构](doc/architecture.md)
2. [技术栈](doc/tech-stack.md) · [数据库设计](doc/db-design.md)
3. [API 设计](doc/api-design.md) · [后端模块](doc/backend/modules.md)
4. [LLM 分析](doc/llm-analysis.md) · [前端页面](doc/frontend/pages.md)
5. [Akshare API 参考](doc/akshare-api.md)

各子项目的更细使用说明：

- 后端：[`backend/README.md`](backend/README.md)
- 前端：[`frontend/README.md`](frontend/README.md)
- 采集脚本：[`scripts/README.md`](scripts/README.md)

## 约定

- 提交信息遵循 [Conventional Commits](https://www.conventionalcommits.org/)（Angular 风格），例：`feat(backend): add etf kline endpoint`。
- 提 PR 后 Agent 会按 [`AGENTS.md`](AGENTS.md) 自动执行一次 Code Review 并将结论作为 PR comment。
- `data/`、`*.db`、`*.tsbuildinfo`、`scripts/.venv/` 等已在 `.gitignore` 中，请勿提交。

## 已知限制（MVP）

- “已分析 / 待分析”状态筛选：后端暂未提供按分析状态过滤的接口，前端按当前页客户端过滤。
- 首页 ETF 卡片“已分析”数：`stats` 接口仅给出股票 + ETF 合计的 `analyzedCnt`，ETF 卡片按同一数值计算并封顶 100%。
- 行业 / 管理人下拉选项从已加载数据累积（后端暂无字典接口）。
- K 线默认回溯 5 年窗口（可用 `--start` 扩展更早历史）；ETF K 线仅存不复权数据（新浪源不支持 ETF 复权，详见 [doc/akshare-api.md](doc/akshare-api.md)）。
