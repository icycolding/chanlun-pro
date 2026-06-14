---
name: "quality-gate"
description: "交付前执行质量闸门并汇总结果。Invoke when code changes are complete and ready for handoff."
---

# Quality Gate

## Goal
在交付前统一执行静态检查和验证流程，确保改动可运行、可维护。

## Invoke When
- 已完成代码修改，准备交付给用户
- 需要确认没有引入新的 lint/typecheck/test 失败
- 需要形成结构化的验证结果摘要

## Workflow
1. 读取项目定义的 lint、typecheck、test、build 命令
2. 按顺序执行并记录失败项
3. 逐项修复失败并重跑直到通过
4. 输出变更摘要与验证结果

## Report Template
- 变更范围
- 验证命令
- 结果状态
- 已知风险与后续建议
