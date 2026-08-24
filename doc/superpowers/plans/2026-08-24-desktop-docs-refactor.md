# Desktop Docs Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor desktop documentation per issue #49 — restructure `doc/desktop.md` by concern, fix drift (CORS behavior, env vars), and sync README / CLAUDE.md / doc index so all four stay consistent.

**Architecture:** Keep `doc/desktop.md` as the single maintenance point for desktop topics (no file split — all inbound links keep working), restructured into clear top-level sections: 概述与定位 / 架构 / 开发模式 / Sidecar 生命周期 / 数据库选择 / 打包与发布 / 注意事项与已知限制. README、CLAUDE.md 只保留摘要并指向该文档。

**Tech Stack:** Markdown docs only. No code changes.

**Spec:** Issue #49 (`gh issue view 49`) — goals & acceptance criteria in the issue body.

## Global Constraints

- 桌面端定位表述保持：「桌面端是查看器：不新增采集功能、不修改 Python 脚本行为、不影响浏览器端」。
- 提交信息遵循 Conventional Commits（Angular），subject 英文祈使句 ≤50 字符。
- 与用户交流用简体中文；代码/命令/文件名保留英文。
- PR 创建后必须按 AGENTS.md 流程加载 `.pi/skills/review-and-comment-pr/SKILL.md` 做 review 并把结论 comment 到 PR。

## 事实核对结果（已验证，写入文档时以此为准确值）

| 事实 | 验证来源 |
|------|----------|
| 命令 `npx --prefix frontend tauri dev/build` 在仓库根可用，CLI 能发现 `desktop/tauri.conf.json` | 实测 `tauri info` 输出 devUrl/frontendDist |
| sidecar 注入 `PORT=3100`、`DB_PATH=<resolve_db_path>`、`CORS_ORIGIN`（debug 加 `http://localhost:5173`） | `desktop/src/lib.rs:70-79` |
| `CORS_ORIGIN` 取值：release `tauri://localhost,http://tauri.localhost`；debug 追加 `http://localhost:5173`；后端缺省（未设）时 `origin: true` 放行全部 | `desktop/src/lib.rs:62-74`、`backend/src/main.ts:12-16` |
| sidecar 产物 `desktop/binaries/backend-<rustc host-tuple>[.exe]` | `backend/build-sidecar.mjs:42-46` |
| pkg assets 含 `node_modules/better-sqlite3/prebuilds/*.node` 与 `database/schema.sql` | `backend/package.json` `pkg.assets` |
| identifier `com.mstock.desktop` → 配置目录 `~/Library/Application Support/com.mstock.desktop/` | `desktop/tauri.conf.json` |
| CI：`release` 分支 push 或 `workflow_dispatch`；macos-latest(arm64) + macos-13(x64) + windows-latest；draft release；仅 `GITHUB_TOKEN`，无签名密钥 | `.github/workflows/desktop-release.yml` |
| DbPicker：`invoke('set_db_path')` + `message('已保存数据库路径，请重启应用生效。')` | `frontend/src/components/DbPicker.tsx:18-20` |
| ETF K 线默认 `adjust=qfq` 与库内 adjustflag=3 不匹配（预存在 bug） | `frontend/src/api/index.ts:83` |
| `resolve_db_path` 优先级：db_path.txt → cwd 及其 parent 下 `data/market.db` → 配置目录新建空库 | `desktop/src/lib.rs:35-51` |

---

### Task 1: 重构 `doc/desktop.md`

**Files:**
- Modify: `doc/desktop.md`（整篇重排）

**Interfaces:**
- Produces: 单一维护点的桌面文档；README/CLAUDE/doc 索引引用的锚点不变（文件路径不变）。

新结构（内容全部保留现有事实，新增 CORS 小节，修正组织方式）：

1. `## 概述与定位` —— 合并现 §1 概述 + 开头定位段；保留四要点（壳/前端/后端/采集）+ 查看器三不原则。
2. `## 架构` —— ASCII 图 + 关键运行参数表（**表加一行 `CORS_ORIGIN`**：sidecar 注入，见开发模式）；关键文件表不动（已与代码一致）。
3. `## 开发模式`（原「开发与构建命令」§4 改造）—— 前置条件；桌面开发命令（注明在仓库根执行、CLI 自动发现 `desktop/tauri.conf.json`）；**新增小节「CORS 行为」**：
   - 后端读 `CORS_ORIGIN`（逗号分隔白名单，`backend/src/main.ts`），未设置时放行全部 origin（浏览器 dev / `npm run start:dev` 场景）。
   - 桌面端由 Rust 注入：release 仅 Tauri WebView 来源（macOS `tauri://localhost`、Windows/Linux `http://tauri.localhost`）；debug 构建额外放行 `http://localhost:5173`（tauri dev 时页面来源是 Vite devUrl）。
   - 动机一句话：后端常驻 localhost:3100，禁缺省放行全部，防任意网页读写（含触发 LLM 配额）。
4. `## Sidecar 生命周期`（原 §5）—— 图中 env 行补 `CORS_ORIGIN`；要点同步。
5. `## 数据库选择流程`（原 §6）—— 内容不变（已核实）。
6. `## 打包与发布`（合并原 §4.4 CI 发布 + §7 打包/分发/签名 + §8 注意事项 1/2）—— sidecar 打包三步、应用打包、签名与公证现状、CI 发布（含 macos-13 跑 x64 的细节）、本地构建 `.env` 内嵌警告与 headless DMG `CI=true` 提示归入此节。
7. `## 已知限制`（原 §9 + 原 §8 注意事项 3/4 中仍属限制性质的条目酌情就近安放）—— 五条已知限制保留，编号更新。

- [ ] **Step 1:** 按上述结构重写 `doc/desktop.md`，所有命令/路径/取值用「事实核对结果」表的准确值。
- [ ] **Step 2:** 通读检查：无残留 `src-tauri` 字样；锚点链接（如 `#9-已知限制`）随新编号更新；表格管道对齐不做硬性要求。

### Task 2: 同步根目录 `README.md`

**Files:**
- Modify: `README.md`（仓库结构树 + 桌面应用节）

- [ ] **Step 1:** 「仓库结构」树在 `scripts/` 之后加一行 ``├── desktop/          # Tauri 2 桌面壳（Rust）+ sidecar binaries``（缩进风格与现有一致）。
- [ ] **Step 2:** 「桌面应用（Tauri）」节事实复核：HashRouter、直连 `http://localhost:3100/api`、查看器定位、更换数据库重启生效——均已属实，仅确保措辞与 desktop.md 一致并在结尾强调「详细说明以 doc/desktop.md 为单一维护点」。

### Task 3: 同步 `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md`（架构要点桌面 bullet + 环境变量 bullet）

- [ ] **Step 1:** 桌面 bullet 补一句 CORS：Rust spawn 时注入 `PORT=3100`/`DB_PATH`/`CORS_ORIGIN`（仅放行 Tauri WebView 来源，tauri dev 另放行 :5173）。
- [ ] **Step 2:** 环境变量 bullet 补 `CORS_ORIGIN`（后端 CORS 白名单，逗号分隔；未设置时放行全部）。

### Task 4: 更新 `doc/README.md` 索引

**Files:**
- Modify: `doc/README.md`

- [ ] **Step 1:** 文档列表表加行 `[desktop.md](desktop.md)` | 桌面应用（Tauri）：架构、开发模式、sidecar、打包发布 | 新。

### Task 5: 验证

- [ ] **Step 1:** 对照验收标准逐条自查：(a) 文档与代码一致（抽查 lib.rs/main.ts/build-sidecar.mjs/workflow 数值）；(b) 三处描述（desktop.md/README/CLAUDE.md）无矛盾；(c) `grep -rn "src-tauri" README.md CLAUDE.md doc/` 为空；(d) 相对链接目标存在。
- [ ] **Step 2:** 纯文档改动，无需跑测试套件；确认 `git diff --stat` 仅触及 4 个 .md 文件。

### Task 6: 提交、PR 与自动 Review

- [ ] **Step 1:** 建分支 `docs/desktop-refactor`；提交 `docs(desktop): refactor by concerns and sync refs`（subject ≤50 字符，可拆两个 commit：主重构 + 索引/README 同步，酌情）。
- [ ] **Step 2:** push 并 `gh pr create`（正文中文，Summary/Test plan 结构，关联 `Closes #49`）。
- [ ] **Step 3:** 按 AGENTS.md 加载 `.pi/skills/review-and-comment-pr/SKILL.md` 执行只读 review，结论分级 Critical/Important/Minor + Ready to merge? 结论，`gh pr comment <N> --body-file report.md` 写入 PR。
