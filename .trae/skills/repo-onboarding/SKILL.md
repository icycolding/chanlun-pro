---
name: "repo-onboarding"
description: "快速梳理代码库架构、入口与关键模块。Invoke when user asks to understand an unfamiliar repository before coding."
---

# Repository Onboarding

## Goal
帮助模型在开始改代码前，快速建立对仓库的结构化理解，减少误改和漏改。

## Invoke When
- 用户让你“先看看项目结构”
- 用户问“这个项目怎么跑、核心模块在哪”
- 任务涉及跨多个目录修改，需要先摸清依赖关系

## Workflow
1. 先做高层检索，识别应用类型、框架和主入口
2. 找配置文件与脚本，确认构建、测试、Lint、Typecheck 命令
3. 映射目录职责，标出核心业务流与边界模块
4. 输出最小可行动路径：先改哪里、后改哪里、如何验证

## Output Requirements
- 用简短结构化要点描述“入口、核心流、风险点”
- 给出与当前任务直接相关的文件清单
- 明确后续验证命令与通过标准
