---
name: "meta-dispatcher-task-orchestrator"
description: "自动拆解复杂需求并路由执行。Invoke when request has multiple modules, dependencies, or parallel tracks."
---

# Meta Dispatcher & Task Orchestrator

## Goal
把复杂任务拆成可执行子任务，并按优先级和依赖关系组织推进。

## Invoke When
- 需求涉及多个模块或多阶段
- 需要并行推进与统一收敛
- 任务边界不清晰，容易漏项

## Workflow
1. 识别目标、约束和风险
2. 拆分子任务并定义依赖
3. 分配执行顺序与验证标准
4. 汇总结果并给出下一步路径
