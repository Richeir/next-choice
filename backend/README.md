# next-choice Backend

Nest.js 后端，为前端提供 REST API 并读写 SQLite（数据由 Akshare Python 采集脚本写入 `data/market.db`）。

## 技术栈

- Nest.js 10 + TypeScript 5
- better-sqlite3 13（同步 SQLite 驱动；schema 复用 `database/schema.sql`）
- @nestjs/schedule（预留定时分析）、class-validator（参数校验）

> 注：`better-sqlite3` 采用 ^13 以兼容 Node ≥22/26 编译，技术栈基线见 `doc/tech-stack.md`。

## 快速开始

```bash
cd backend
npm install
# 开发模式（热重载）
npm run start:dev
# 生产模式
npm run build && npm run start:prod
```

服务默认监听 `http://localhost:3100`，全局前缀 `/api`，默认连接仓库根 `data/market.db`（可用 `DB_PATH` 覆盖，`PORT` 覆盖端口）。

> 单进程部署：仓库内已构建 `frontend/dist` 时，`start:prod` 会同进程托管前端页面（非 `/api` 的无扩展名 GET 回退到 `index.html`），单端口即可访问完整应用；未构建时自动退化为纯 API 服务。

## 测试

```bash
npm test          # 单元测试（scoring / mapper / technical-analysis）
npm run test:e2e  # e2e 测试（覆盖全部接口，使用临时数据库，不污染真实数据）
```

## 接口一览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/stats` | 首页统计（内存缓存 10 分钟） |
| GET | `/api/stocks` / `/api/etfs` | 列表（分页/关键字/过滤/排序/评级） |
| GET | `/api/stocks/:code` / `/api/etfs/:code` | 详情（不存在返回 404） |
| GET | `/api/stocks/:code/analysis` / `/api/etfs/:code/analysis` | 分析历史 |
| GET | `/api/stocks/:code/kline` / `/api/etfs/:code/kline` | K 线（frequency/adjust/limit/start/end） |
| POST | `/api/stocks/:code/analyze` / `/api/etfs/:code/analyze` | 触发异步分析（返回 jobId） |
| GET | `/api/jobs/:jobId` | 查询分析任务状态 |
| GET/PUT | `/api/config/analysis` | 读写分析配置（含提示词模板） |

详细约定见 `doc/api-design.md`、`doc/backend/modules.md`。

## 目录结构

```
backend/src/
├── main.ts / app.module.ts
├── common/            # 评分换算、snake→camel 映射、查询 DTO
├── config/            # 分析默认配置 + 合并 DB 覆盖
├── database/          # better-sqlite3 连接 + schema.sql
├── jobs/              # 内存任务队列（JobManager）
└── modules/
    ├── stats/         # 首页统计
    ├── securities/    # 股票/ETF 列表、详情、分析历史
    ├── kline/         # K 线查询
    ├── analysis/      # 技术面分析 + LLM 接口 + 触发/任务
    └── config-api/    # 配置读写
```

## LLM 说明

- 默认提示词/模型配置见 `src/config/analysis.config.json`；`PUT /api/config/analysis` 可在线覆盖（写入 `analysis_config` 表，DB 优先）。
- 未配置 `ANALYSIS_LLM_API_KEY` 时，分析自动回退到**纯技术面评分**（`doc/db-design.md` §6 规则）；配置 key 后可接入真实 LLM（LLM 服务接口已预留，见 `src/modules/analysis/llm.service.ts`）。
