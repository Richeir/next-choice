# 技术栈说明

本文档固定 MVP0 的技术选型与版本。

## 1. 技术栈总览

| 层 | 技术 | 版本 | 说明 |
|----|------|------|------|
| 前端框架 | React | 18.x | 构建富交互 UI |
| 前端语言 | TypeScript | 5.x | |
| 前端构建 | Vite | 5.x | 开发/构建工具 |
| 路由 | React Router | 6.x | 页面路由 |
| HTTP 客户端 | Axios | 1.x | 调用后端 API |
| 后端框架 | Nest.js | 10.x | 提供 REST API |
| 后端语言 | TypeScript | 5.x | |
| ORM / 访问层 | better-sqlite3 | 11.x | 同步 SQLite 驱动 |
| 数据库 | SQLite | 3.x | 本地持久化（内置） |
| LLM SDK | OpenAI Node SDK（或对应厂商） | 4.x | 调用大模型 |
| 数据源 | Akshare | 1.18.x | Python Library，采集脚本（腾讯/新浪/雪球/同花顺源） |
| 采集脚本语言 | Python | 3.11+ | 独立脚本拉取 Akshare |

> 版本为锁定基线，后续如有升级需在本文档同步更新并标注变更原因。

## 2. 目录结构规划

```
next-choice/
├── frontend/          # React + Vite + TS
│   ├── src/
│   │   ├── pages/     # 首页 / 列表 / 详情
│   │   ├── components/
│   │   ├── api/       # Axios 封装
│   │   └── App.tsx
│   └── package.json
├── backend/           # Nest.js + TS
│   ├── src/
│   │   ├── modules/   # 各业务模块
│   │   ├── config/    # 全局配置（含 LLM 提示词模板）
│   │   └── main.ts
│   └── package.json
├── scripts/           # Python 采集脚本（Akshare）
│   ├── fetch_data.py
│   └── akshare_source.py
├── data/              # SQLite 数据库文件（本地）
└── doc/               # 本文档目录
```

## 3. 版本锁定原因

- **Nest.js 10**：成熟稳定的主流大版本，社区支持充分。
- **React 18**：并发特性稳定，生态成熟。
- **better-sqlite3**：同步 API，Nest.js 内使用简单直观，适合本地单机 SQLite。
- **Vite 5**：开发体验好、启动快，配合 React 主流方案。
- **Akshare 1.18.x**：数据源固定版本，避免上游接口变动影响采集（东财源在当前网络不可用，仅用非东财源，见 doc/akshare-api.md）。

## 4. 环境要求

- Node.js ≥ 20（同时运行 Nest.js 与 Vite）
- Python ≥ 3.11（运行采集脚本）
- 无外部数据库依赖（SQLite 为文件型，开箱即用）
