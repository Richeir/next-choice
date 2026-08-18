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

### 0. 准备 PR body 草稿并确保有关联 issue（在 push / 创建 PR 之前）

本步骤产出两个变量：`PR_BODY`（PR body 草稿）和 `ISSUE_NUMBER`（关联的 issue 号，可能由 0d 创建）。

**唯一合法顺序**：0a/0b 准备并检查 → 0c/0d 建 issue（必要时）→ 0e 把 `Closes #N` 追加到 `PR_BODY`。禁止 Agent 凭直觉先写 PR body 再回头补 issue。

#### 0a. 准备 `PR_BODY`

按以下优先级确定 `PR_BODY` 来源：

1. **用户提供的本地文件**：`$PR_BODY_FILE` 环境变量，或仓库根目录的 `.git/PR_BODY.md`、`PR_BODY.md`。
2. **Agent 自行构造**：基于 0c 的 commit + diff 摘要生成（参考 0d 的"摘要"段规则）。

```bash
PR_BODY=""
if [ -n "$PR_BODY_FILE" ] && [ -f "$PR_BODY_FILE" ]; then
  PR_BODY=$(cat "$PR_BODY_FILE")
elif [ -f .git/PR_BODY.md ]; then
  PR_BODY=$(cat .git/PR_BODY.md)
elif [ -f PR_BODY.md ]; then
  PR_BODY=$(cat PR_BODY.md)
fi
# 上述文件都没有时，PR_BODY 留空，Agent 在 0d 之前补一段基于 commit + diff 的摘要。
```

> ⚠️ 不允许把 `<占位符>` 字面量塞进 `PR_BODY`；留空比放占位符安全。

#### 0b. 检查 `PR_BODY` 是否已含关联关键词

```bash
if echo "$PR_BODY" | grep -qE "(Closes|Fixes|Resolves)\s+#[0-9]+"; then
  ISSUE_NUMBER=$(echo "$PR_BODY" | grep -oE "(Closes|Fixes|Resolves)\s+#[0-9]+" | head -1 | grep -oE "[0-9]+")
  echo "PR body already references issue #$ISSUE_NUMBER, skipping issue creation."
  SKIP_ISSUE_CREATION=1
else
  echo "No issue linked. Will create one."
fi
```

- 命中 → `SKIP_ISSUE_CREATION=1`，跳过 0c/0d，保留 `PR_BODY` 原样，进入 Step 1。
- 未命中 → 进入 0c。

#### 0c. 生成 issue 标题与 body（基于当前 PR 内容）

**先看真实改动，再写 issue**——不允许只根据 commit message 凭空生成。

```bash
BASE="origin/main"
HEAD="$(git rev-parse --abbrev-ref HEAD)"

git diff --stat "$BASE...$HEAD"                       # 改动概览（必须真实读取）
git log "$BASE..$HEAD" --pretty=format:"%s%n%b%n---"  # Commit 列表
```

**标题生成规则**（规则与命令示例必须能互相印证）：

- ≤ 50 字符，祈使句式。
- **必须去掉 Conventional Commits 的 type/scope 前缀**（如 `docs(skills):`、`feat:`、`fix(api):`）——issue 标题不需要提交元数据。
- 多个 commit 主题分散时取最能代表整体意图的一个；必要时手动合并短语，例如 `add foo feature`、`fix bar bug`、`refactor: extract baz helper`。
- 去掉结尾的句号、表情、与本任务无关的后缀。
- 长度超过 50 字符时，在最近的空格处截断并加 `...`（避免切到单词中间）。

```bash
# 从第一条 commit subject 提取标题：先 sed 去掉 type/scope 前缀，再 awk 在边界处截断
RAW_SUBJECT=$(git log "$BASE..$HEAD" --pretty=format:"%s" | head -1)
ISSUE_TITLE=$(echo "$RAW_SUBJECT" \
  | sed -E 's/^[a-z]+(\([^)]+\))?:\s*//' \
  | awk '{ if (length($0) > 50) print substr($0, 1, 47) "..."; else print $0 }')
```

**Body（三段式总结当前 PR 的内容）**：

1. **摘要**：一句话说明这个 PR 要做什么（基于 commits + diff 整体提炼）。
2. **改动概览**：`git diff --stat` 输出原文。
3. **Commits**：`git log` 每条一行（含 hash 短值便于追溯）。

#### 0d. 创建 issue

```bash
cat > /tmp/issue_body.md <<EOF
## 摘要
$(echo "$RAW_SUBJECT" | sed -E 's/^[a-z]+(\([^)]+\))?:\s*//')

## 改动概览
\`\`\`
$(git diff --stat "$BASE...$HEAD")
\`\`\`

## Commits
$(git log "$BASE..$HEAD" --pretty=format:"- %h %s")

---
本 issue 由 Agent 在创建 PR 前自动生成。
EOF

ISSUE_URL=$(gh issue create --title "$ISSUE_TITLE" --body-file /tmp/issue_body.md)
ISSUE_NUMBER=$(echo "$ISSUE_URL" | grep -oE '[0-9]+$')
echo "Created issue #$ISSUE_NUMBER: $ISSUE_URL"
```

#### 0e. 把 `Closes #<ISSUE_NUMBER>` 追加到 `PR_BODY` 末尾

```bash
PR_BODY="${PR_BODY}

Closes #$ISSUE_NUMBER"
```

> 如果 0b 已命中 `Closes/Fixes/Resolves #N` → **不要**改写或重复追加，沿用原 `PR_BODY` 即可。

### 1. 创建 PR

```bash
gh pr create --title "<title>" --body "$PR_BODY" --base main
# base 不是 main 时：gh pr create --base <实际 base>
```

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
- `PR_BODY` 必须由 Step 0a 显式提供（本地文件 / Agent 构造），禁止把 `<占位符>` 字面量塞进去。
- **issue 标题必须精炼（≤ 50 字符）**，祈使句式，**必须去掉 Conventional Commits 的 type/scope 前缀**（如 `docs(skills):`）；禁止照搬多行 commit subject。
- **issue body 必须先看 `git diff` 再写**——不允许脱离 diff 内容凭空生成摘要。
- PR body 已经包含 `Closes/Fixes/Resolves #N` 时，**不要**重复创建 issue，也**不要**改写现有关键词。
- 如果 base 分支不是 `origin/main`，先把 `BASE` 调整为实际 base，再跑 diff / log。
