# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 工作约定

### 沟通偏好

- Agent 与用户交流、生成解释、总结、报告、PR 评论等说明性内容时，统一使用**简体中文**。
- 代码、命令、文件名、API 名称、英文术语、提交信息、代码注释等保留英文原文不动。

### 提交规范（Conventional Commits / Angular）

提交信息格式：`<type>(<scope>): <subject>`

- type：`feat` / `fix` / `docs` / `refactor` / `chore` / `style` / `test` / `perf` / `build` / `ci`
- subject：英文、祈使句、小写开头、≤50 字符、结尾不加句号。
- 需要背景时正文用空行分隔、每行 ≤72 字符；破坏性变更写 `BREAKING CHANGE:`。
- 本地无 git 身份配置时，用 `git -c user.name=... -c user.email=...` 临时指定。

### 代码 Review 工作流（提 PR 后自动执行）

**规则：提交/推送一个 PR 后，Agent 必须自动执行一次 Code Review，并把 Review 结论以 comment 形式写入该 PR。**

流程：

1. **推送并创建 PR**（用 `gh pr create`），拿到 PR 号。
2. **触发 Review**：加载 `.pi/skills/review-and-comment-pr/SKILL.md`，按其指引 review 该 PR 的改动。
3. **把 Review 结论写入 PR**：生成 review 报告后，用 `gh` 把报告作为 comment 发布到该 PR：
   ```bash
   gh pr comment <PR_NUMBER> --body-file <review_report.md>
   ```
   或用 `gh api` 提交正式的 code review（含逐文件 inline comment 时）。

说明：

- Review 采用只读审查：可用 `git diff <base>..<head>`、`git show`、`git log` 检查，不得改动工作区/分支。
- 结论需分级：`Critical`（必须修复）/ `Important`（应当修复）/ `Minor`（可选），并给出 **Ready to merge? Yes/No/With fixes** 的明确结论。

## 项目

股票/ETF 分析 Demo：Akshare（Python）采集行情 → SQLite → Nest.js REST → React 前端展示，可选 LLM 分析。完整链路与页面说明见根目录 [`README.md`](README.md)。

## 运行与测试命令

根目录统一脚本（Node 部分，首次需 `npm install && npm run install:all`）：

```bash
npm run dev        # 并行启动 backend(:3100) 与 frontend(:5173)
npm run build      # 先 frontend 后 backend 构建
npm run start      # 单进程生产模式：托管 frontend/dist 与 /api（未构建则纯 API）
npm test           # backend jest + frontend vitest（Python 用例仍走 pytest）
```

数据采集脚本（Python，首次需 `python3 -m venv scripts/.venv && scripts/.venv/bin/pip install -r scripts/requirements.txt`）：

```bash
cd scripts
.venv/bin/python fetch_data.py --db ../data/market.db --update-stock-list
.venv/bin/python fetch_data.py --db ../data/market.db --update-etf-list
.venv/bin/python fetch_data.py --db ../data/market.db --fetch-etf-kline --freq daily,weekly,monthly --start 2026-01-05
.venv/bin/python -m pytest tests -q -m "not e2e"                 # 仅单元测试
.venv/bin/python -m pytest tests -q                              # 全部（e2e 会真实连 Akshare）
.venv/bin/python -m pytest tests/test_akshare_source.py -q       # 单个文件
```

后端（Nest.js，`backend/`）：

```bash
cd backend
npm run start:dev      # 开发热重载，默认 :3100，全局前缀 /api
npm test               # jest 单元测试
npm run test:e2e       # e2e（用临时库，不污染真实数据）
```

前端（React + Vite，`frontend/`）：

```bash
cd frontend
npm run dev            # :5173，/api 已代理到 :3100
npm test               # vitest
npm run build          # tsc -b && vite build
```

## 架构要点

- **SQLite schema 单一来源**：`backend/database/schema.sql`（11 张表），Python（`scripts/db.py`）与 Nest.js 后端共用；默认库 `data/market.db`（gitignored，不入库）。
- **K 线幂等**：主键 `UNIQUE(code, date, adjustflag)`，脚本可重复运行覆盖；周/月 K 由日 K 本地重采样（`scripts/akshare_source.py::resample_kline`），不单独抓取。新浪 ETF 源仅不复权，ETF K 线 `--adjust` 被强制为 3。
- **采集脚本分层**（`scripts/`）：`akshare_source.py` 管抓取/重试退避/列标准化（不感知 SQLite），`db.py` 管读写，`fetch_data.py` 是 CLI 入口。`_normalize_daily` 会把各源原始列统一为 `KLINE_COLS`。
- **后端分层**（`backend/src/`）：`database.service.ts` 持有 better-sqlite3 连接；`modules/*` 每域一组 controller/service/repository；`jobs/job-manager.service.ts` 管理异步分析任务（analyze 返回 jobId，前端轮询）；`common/scoring.ts` 纯技术面评分；`common/mapper.ts` 做行→DTO 映射。
- **分析双模式**：无 `LLM_API_KEY` 时仅技术面评分（开箱即用）；配置后经 `llm.service.ts` 调 OpenAI 兼容接口，提示词模板可由 `GET/PUT /api/config/analysis` 在线覆盖并落库（DB 优先于文件）。
- **前端**（`frontend/src/`）：页面在 `pages/`，列表/筛选/分页通用逻辑收敛在 `components/SecurityListPage.tsx` + `hooks/useListPage.ts`，API 封装在 `api/client.ts`，类型在 `api/types.ts`。
- **环境变量**：`DB_PATH`（覆盖数据库路径）、`PORT`（后端端口）、`LLM_API_KEY`/`LLM_BASE_URL`/`LLM_MODEL`（LLM 分析，见 `.env.example`）、`XQ_TOKEN`（雪球 `xq_a_token` 注入，采集脚本 `--fetch-*-info` 依赖，见 issue #55）。

## 文档索引

深读优先 `doc/`：`architecture.md`（架构与数据流）、`db-design.md`（字段/索引）、`api-design.md`（接口约定）、`akshare-api.md`（接口清单与已知限制）、`llm-analysis.md`。各子项目另有 `backend/README.md`、`frontend/README.md`、`scripts/README.md`。
