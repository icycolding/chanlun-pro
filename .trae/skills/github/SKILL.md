---
name: "github"
description: "Handles GitHub repo search, issues, PR planning, and workflow guidance. Invoke when user asks about GitHub repositories, issues, pull requests, or collaboration on GitHub."
---

# GitHub

Use this skill to help with GitHub-centered work in the workspace.

## Project Fit

- Prefer workflows that match this repository's Python + Flask + Jinja structure
- Keep recommendations practical for financial analysis, news systems, and page-level product work
- Favor changes that are easy to review in PRs with clear scope and low regression risk
- When searching GitHub for references, prioritize reusable implementations for news retrieval, async tasks, vector search, and financial dashboards

## Invoke When

- The user asks to search GitHub for references or prior art
- The user wants help with issues, pull requests, branches, reviews, or release preparation
- The user needs a GitHub-oriented implementation or collaboration workflow
- The user asks how to organize repository work on GitHub

## What This Skill Does

- Breaks down GitHub tasks into practical steps
- Helps draft issue scopes, acceptance criteria, and PR descriptions
- Suggests branch naming, commit grouping, and review checkpoints
- Recommends how to find reusable implementations and prior art on GitHub
- Supports repo collaboration patterns that fit engineering delivery

## Workflow

1. Identify whether the request is about repository discovery, contribution flow, or PR delivery
2. Gather the minimum repo, branch, issue, feature, or deployment context needed
3. Check whether the task is backend, page-level UI, data pipeline, or integration work
4. Recommend or perform the most direct GitHub-oriented workflow
5. Keep outputs structured for copy/paste into issues, PRs, or team discussions

## Project-Specific Guidance

- For news, retrieval, and summarization work, structure issues and PRs around ingestion, storage, search, evidence quality, and UI consumption
- For page changes, separate UI adjustments from backend API or data-model changes when possible to keep review focused
- For bug fixes, include root cause, affected path, regression coverage, and user-visible impact in PR summaries
- For architecture changes, break work into incremental PRs such as data model, API layer, background jobs, and page integration
- For GitHub search, prefer examples involving Flask, SQLAlchemy, Chroma or vector retrieval, async job polling, and financial/news products

## Pull Request Expectations

- State the user problem first
- Summarize root cause or design rationale
- List changed files or modules by responsibility
- Include verification steps and any environment caveats
- Highlight rollout or backfill requirements when data structures change

## Common Outputs

- GitHub search strategy
- Issue template draft
- PR summary draft
- Branch and commit plan
- Review checklist
- Release or merge checklist

## Example Requests

- "帮我整理一个 GitHub PR 描述"
- "去 GitHub 找一个现成的实现思路"
- "给这个功能设计 issue 拆解"
- "帮我规划分支和提交方式"
- "帮我把新闻检索改造拆成几个可合并的 PR"
- "找 Flask + 向量检索 + 异步轮询的 GitHub 参考项目"
