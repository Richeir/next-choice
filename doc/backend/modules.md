# Nest.js 后端模块划分

本文档描述 Nest.js 后端的模块划分、数据访问层与定时任务。

## 1. 模块总览

```
backend/src/
├── main.ts                     # 入口，全局前缀 /api
├── app.module.ts               # 根模块
├── config/                     # 全局配置（含 LLM 提示词模板）
│   ├── analysis.config.json    # 默认提示词/模型配置
│   └── config.module.ts        # 配置读取模块
├── database/
│   ├── database.module.ts      # SQLite 连接（better-sqlite3）
│   ├── database.service.ts     # 连接与查询封装
│   └── schema.sql              # 建表 SQL（与 DB_DESIGN.md 一致）
├── modules/
│   ├── securities/             # 证券信息模块
│   │   ├── securities.module.ts
│   │   ├── securities.controller.ts   # GET /api/stocks、/api/etfs、详情
│   │   ├── securities.service.ts
│   │   └── repository/
│   │       └── stock-info.repository.ts
│   │       └── etf-info.repository.ts
│   ├── kline/                  # K 线模块
│   │   ├── kline.module.ts
│   │   ├── kline.controller.ts        # GET /api/:type/:code/kline
│   │   ├── kline.service.ts
│   │   └── repository/
│   │       └── kline.repository.ts
│   ├── analysis/               # 分析模块
│   │   ├── analysis.module.ts
│   │   ├── analysis.controller.ts     # 查询分析 + 触发分析 + 任务状态
│   │   ├── analysis.service.ts
│   │   ├── llm.service.ts             # 封装 LLM 调用 + JSON 解析
│   │   └── repository/
│   │       └── analysis.repository.ts
│   ├── stats/                  # 首页统计模块
│   │   ├── stats.module.ts
│   │   ├── stats.controller.ts        # GET /api/stats
│   │   └── stats.service.ts
│   └── config-api/             # 配置管理模块
│       ├── config-api.module.ts
│       ├── config-api.controller.ts   # GET/PUT /api/config/analysis
│       └── config-api.service.ts
└── jobs/                       # 分析任务队列（内存）
    ├── job-manager.service.ts  # 任务状态管理
    └── analysis-scheduler.service.ts # 定时分析任务
```

## 2. 模块职责与依赖

| 模块 | 职责 | 依赖 |
|------|------|------|
| `config` | 读取默认配置，合并 DB 覆盖 | database |
| `database` | SQLite 连接、执行 SQL | better-sqlite3 |
| `securities` | 证券基础信息查询 | database |
| `kline` | K 线数据查询 | database |
| `analysis` | 分析历史查询、触发分析、LLM 调用 | database, config, jobs |
| `stats` | 首页统计 | database |
| `config-api` | 分析配置读写 | database, config |
| `jobs` | 分析任务状态、定时调度 | analysis |

**依赖方向**：`controller → service → repository → database`，单向依赖，避免循环。

## 3. 数据访问层（Repository）

- 每个模块的 `repository/` 封装 SQLite 查询，隔离 SQL。
- 返回结构在 Service 层映射为 API 响应（如 `codeName`、`isWorthBuying`）。
- SQLite 用 `better-sqlite3` 同步 API，直接在 Repository 内执行 prepared statements。

**示例：评级排序查询**（取每只最新评级后排序）

```ts
// securities.repository.ts
const rows = db.prepare(`
  SELECT si.code, si.code_name,
         a.rating, a.score, a.signal, a.date AS analysis_date
  FROM stock_info si
  LEFT JOIN (
    SELECT code, rating, score, signal, date,
           ROW_NUMBER() OVER (PARTITION BY code ORDER BY date DESC) AS rn
    FROM stock_analysis
  ) a ON a.code = si.code AND a.rn = 1
  WHERE (:keyword IS NULL OR si.code LIKE '%'||:keyword||'%'
     OR si.code_name LIKE '%'||:keyword||'%')
  ORDER BY CASE a.rating
    WHEN 'S+' THEN 9 WHEN 'S' THEN 8 WHEN 'A+' THEN 7 WHEN 'A' THEN 6
    WHEN 'B+' THEN 5 WHEN 'B' THEN 4 WHEN 'C+' THEN 3 WHEN 'C' THEN 2
    WHEN 'D' THEN 1 ELSE 0 END DESC
  LIMIT :limit OFFSET :offset
`).all(params);
```

## 4. 分析任务管理（jobs）

- 触发分析（`POST /api/:type/:code/analyze`）入队，返回 `jobId`。
- `JobManagerService` 维护 `Map<jobId, {status, result}>`（MVP0 用内存队列，单实例够用）。
- `AnalysisSchedulerService` 用 `@nestjs/schedule` 定时扫描待分析标的，调用 LLM 分析并落库。
- 前端通过 `GET /api/jobs/:jobId` 轮询结果。

## 5. 全局前缀与校验

- `main.ts` 设置 `app.setGlobalPrefix('api')`，使所有路由为 `/api/...`。
- 用 class-validator 对查询参数与请求体做校验（分页范围、评级枚举、日期格式）。
- 统一异常过滤器输出 `{ statusCode, message, error }`。
