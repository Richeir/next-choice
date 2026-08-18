---
name: review-and-comment-pr
description: Use after pushing or creating any PR in this repository when no tracking issue was opened or an automated code review comment is needed.
---

# Review and Comment on PR

按 AGENTS.md 的「代码 Review 工作流」执行：**创建 PR 前**自动确保有对应的 issue（必要时自动创建），**PR 创建后**自动 review 并把结论写成 PR comment。

## 前提

- 已用 `gh auth status` 确认登录（协议 ssh，token 已配置）。
- `gh` CLI 可用（`command -v gh`）。
- 工作区当前分支包含即将推送 / 已推送的改动，且能定位到 base 分支（默认 `origin/main`）。

## 步骤

### 0. 确保有对应的 issue（在 push / 创建 PR 之前）

#### 0a. 检查是否已经有关联 issue

从 PR body 草稿或本地备注里搜索 GitHub 关键词：`Closes #N` / `Fixes #N` / `Resolves #N`。

```bash
PR_BODY="<本次 PR 的草稿 body>"

if echo "$PR_BODY" | grep -qE "(Closes|Fixes|Resolves)\s+#[0-9]+"; then
  ISSUE_NUMBER=$(echo "$PR_BODY" | grep -oE "(Closes|Fixes|Resolves)\s+#[0-9]+" | head -1 | grep -oE "[0-9]+")
  echo "PR body already references issue #$ISSUE_NUMBER, skipping issue creation."
else
  echo "No issue linked. Will create one."
fi
```

- 如果命中 → 提取 `ISSUE_NUMBER`，跳过 0b/0c，直接进入 step 1。
- 如果没命中 → 进入 0b。

#### 0b. 准备 issue 标题与 body（基于当前 PR 内容）

**先看真实改动，再写 issue**——不允许只根据 commit message 凭空生成。

```bash
BASE="origin/main"
HEAD="$(git rev-parse --abbrev-ref HEAD)"

# 改动概览（必须真实读取）
git diff --stat "$BASE...$HEAD"

# Commit 列表（标题 + body）
git log "$BASE..$HEAD" --pretty=format:"%s%n%b%n---"
```

生成规则：

- **title（必须精炼，≤ 50 字符，祈使句式，模仿 Conventional Commits 风格）**：
  - 优先从 `git log` 的第一条 commit subject 提炼。
  - 如果多个 commit 主题分散，取最能代表整体意图的一个；必要时手动合并短语，例如 `add foo feature`、`fix bar bug`、`refactor: extract baz helper`。
  - 去掉结尾的句号、表情、与本任务无关的后缀。

- **body（三段式总结当前 PR 的内容）**：
  1. **摘要**：一句话说明这个 PR 要做什么（基于 commits + diff 整体提炼）。
  2. **改动概览**：`git diff --stat` 输出原文。
  3. **Commits**：`git log` 每条一行（含 hash 短值便于追溯）。

#### 0c. 创建 issue

```bash
# 把上面的内容写到临时文件
cat > /tmp/issue_body.md <<'EOF'
## 摘要
<一句话说明>

## 改动概览
<git diff --stat 输出>

## Commits
<git log 输出>

---
本 issue 由 Agent 在创建 PR 前自动生成。
EOF

ISSUE_URL=$(gh issue create \
  --title "<精炼标题>" \
  --body-file /tmp/issue_body.md)

ISSUE_NUMBER=$(echo "$ISSUE_URL" | grep -oE '[0-9]+$')
echo "Created issue #$ISSUE_NUMBER: $ISSUE_URL"
```

### 1. 创建 PR（body 追加 `Closes #N`）

把 `Closes #<ISSUE_NUMBER>` 追加到 PR body 末尾：

```bash
FULL_BODY="$PR_BODY

Closes #$ISSUE_NUMBER"

gh pr create --title "<title>" --body "$FULL_BODY"
```

> 如果 0a 已命中 `Fixes #N` 等已有关键词，**不要**改写或重复追加，沿用原 body 即可。

### 2. 确认 PR 号与审查范围

```bash
gh pr list --state open
git fetch origin
git diff --stat origin/main...<head-branch>
git diff origin/main...<head-branch>
```

### 3. 只读审查

- 用 `git diff`、`git show`、`git log` 检查改动，**不要改动**工作区、index、HEAD 或分支。
- 需要看历史版本时，用 `git worktree add /tmp/review-<sha> <sha>` 开临时副本，绝不移动 HEAD。
- 核对：计划/需求是否满足、错误处理、边界情况、测试是否覆盖真实行为、文档是否同步、有无明显 bug。

### 4. 产出分级结论

生成 review 报告，含：

- **Strengths**（具体肯定）
- **Issues**：`Critical` / `Important` / `Minor`，每条含 `文件:行号`、问题、影响、修复建议
- **Recommendations**
- **Assessment**：`Ready to merge? Yes | No | With fixes` + 简短理由

写入临时文件：

```bash
cat > /tmp/review_report.md <<'EOF'
...
EOF
```

### 5. 把 Review 写为 PR comment

```bash
gh pr comment <PR_NUMBER> --body-file /tmp/review_report.md
```

需要正式 review（而非普通 comment）或逐文件 inline 时：

```bash
gh api -X POST repos/:owner/:repo/pulls/<PR_NUMBER>/reviews \
  --input - <<'JSON'
{"commit_id": "<head_sha>", "event": "COMMENT", "body": "<markdown review>"}
JSON
```

### 6. 确认发布成功

```bash
gh pr view <PR_NUMBER> --comments   # 应能看到刚发布的 comment
```

## 规则

- Review 必须基于真实读取的代码，不臆测。
- 结论需给明确 verdict，不得含糊。
- 若发现 critical/important 问题，在 PR 里明确指出，由实现方决定是否修复后再合入。
- **issue 标题必须精炼（≤ 50 字符）**，祈使句式，模仿 Conventional Commits 风格；禁止照搬多行 commit subject。
- **issue body 必须先看 `git diff` 再写**——不允许脱离 diff 内容凭空生成摘要。
- PR body 已经包含 `Closes/Fixes/Resolves #N` 时，**不要**重复创建 issue，也**不要**改写现有关键词。
- 如果 base 分支不是 `origin/main`，先把 `BASE` 调整为实际 base，再跑 diff / log。
