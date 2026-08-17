---
name: review-and-comment-pr
description: Review a pull request after it is created and write the review verdict as a comment on the PR via gh. Use after pushing/creating any PR in this repository.
---

# Review and Comment on PR

按 AGENTS.md 的「代码 Review 工作流」执行：提 PR 后自动 review，并把结论写成 PR comment。

## 前提

- 已用 `gh auth status` 确认登录（协议 ssh，token 已配置）。
- `gh` CLI 可用（`command -v gh`）。

## 步骤

### 1. 确认 PR 号与审查范围

```bash
# 最新 PR 号（若刚创建可用输出里的 URL/编号）
gh pr list --state open
# 审查范围：base 分支 vs head 分支
git fetch origin
git diff --stat origin/main...<head-branch>
git diff origin/main...<head-branch>
```

### 2. 只读审查

- 用 `git diff`、`git show`、`git log` 检查改动，**不要改动**工作区、index、HEAD 或分支。
- 需要看历史版本时，用 `git worktree add /tmp/review-<sha> <sha>` 开临时副本，绝不移动 HEAD。
- 核对：计划/需求是否满足、错误处理、边界情况、测试是否覆盖真实行为、文档是否同步、有无明显 bug。

### 3. 产出分级结论

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

### 4. 把 Review 写为 PR comment

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

### 5. 确认发布成功

```bash
gh pr view <PR_NUMBER> --comments   # 应能看到刚发布的 comment
```

## 规则

- Review 必须基于真实读取的代码，不臆测。
- 结论需给明确 verdict，不得含糊。
- 若发现 critical/important 问题，在 PR 里明确指出，由实现方决定是否修复后再合入。
