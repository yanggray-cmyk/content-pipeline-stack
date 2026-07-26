# GitHub Actions workflows

此目录由 main agent 维护, 装运维任务到 `content-pipeline-stack` repo.

## Workflows

### `close-stale-prs.yml`

- **触发**: `workflow_dispatch` (Actions tab 手动 Run workflow)
- **用途**: 关 stale/toxic PRs + squash merge 干净的 PR
- **由 main agent 创建**: 2026-07-26 17:42
- **背景**: 见 https://github.com/yanggray-cmyk/content-pipeline-stack/pull/10 描述

## 权限

- `contents: write` — merge PR 必需
- `pull-requests: write` — close PR + 留评论

`GITHUB_TOKEN` 由 GitHub 自动注入, 权限限死本 repo, 不暴露给 main agent.

## 流程

1. Cove 在 Actions tab 选这个 workflow
2. 填默认 inputs (close=6 7 8 / merge=9)
3. Run workflow
4. 完成后 PR list 全 closed, main HEAD 包含 strategy pattern squash commit
