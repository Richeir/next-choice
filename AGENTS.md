# next-choice (AGENTS.md)

> 本文件定义项目约定与 Agent 工作流。Agent 在本仓库内工作时必须遵循。

## 项目概览

- Next.js demo 项目，含 BaoStock 行情数据采集（Python）与 Nest.js 后端。
- 关键目录：
  - `backend/database/schema.sql`：SQLite schema 单一来源（Python 脚本与后端共用）。
  - `scripts/`：数据采集脚本（BaoStock -> SQLite），含 `fetch_data.py`、`db.py`、`transform.py`。
  - `doc/`：设计文档（架构、DB、BaoStock API、LLM 分析等）。
- 默认数据入库路径：`data/market.db`。

## 提交规范（Conventional Commits / Angular）

提交信息格式：`<type>(<scope>): <subject>`

- type：`feat` / `fix` / `docs` / `refactor` / `chore` / `style` / `test` / `perf` / `build` / `ci`
- subject：英文、祈使句、小写开头、≤50 字符、结尾不加句号。
- 需要背景时正文用空行分隔、每行 ≤72 字符；破坏性变更写 `BREAKING CHANGE:`。
- 本地无 git 身份配置时，用 `git -c user.name=... -c user.email=...` 临时指定。

## 代码 Review 工作流（提 PR 后自动执行）

**规则：提交/推送一个 PR 后，Agent 必须自动执行一次 Code Review，并把 Review 结论以 comment 形式写入该 PR。**

流程：

1. **推送并创建 PR**（用 `gh pr create`），拿到 PR 号。
2. **触发 Review**：加载 `.pi/skills/review-and-comment-pr/SKILL.md`，按其指引 review 该 PR 的改动。
3. **把 Review 结论写入 PR**：生成 review 报告后，用 `gh` 把报告作为 comment 发布到该 PR：
   ```bash
   gh pr comment <PR_NUMBER> --body-file <review_report.md>
   ```
   或用 `gh api` 提交正式的 code review（含逐文件 inline comment 时）。

### 说明

- Review 采用只读审查：可用 `git diff <base>..<head>`、`git show`、`git log` 检查，不得改动工作区/分支。
- 结论需分级：`Critical`（必须修复）/ `Important`（应当修复）/ `Minor`（可选），并给出**Ready to merge? Yes/No/With fixes** 的明确结论。
- 若 Agent 自身缺少执行该流程的上下文，先读本文件引用的 skill 再执行。

## 合并策略

- **PR 一律不允许 Agent 自动合并（auto-merge）**。Agent 完成 review 并给出结论后，由仓库维护者人工决定是否合并。
- Agent **不得**调用 `gh pr merge`（包括 `--auto`、`--squash`、`--rebase`、`--merge` 等任何形式），也不得开启仓库级的 auto-merge 设置。
- 若 review 结论为 "Ready to merge: Yes"，Agent 只汇报结论与 PR 链接；不要等待或催促合并。
