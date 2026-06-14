---
name: "page-agent"
description: "Builds and refines web pages, page flows, and page-level interactions. Invoke when user asks to create, redesign, optimize, or debug a page experience."
---

# Page Agent

Use this skill for page-level product and implementation work.

## Project Fit

- Prefer existing Flask + Jinja template patterns before introducing new abstractions
- Reuse current Layui, existing utility scripts, and established page behaviors
- Keep page changes aligned with trading, news, research, and settings workflows already present in the project
- Favor compact, information-dense layouts that still preserve clarity for financial use cases

## Invoke When

- The user wants to create a new page
- The user wants to redesign or polish an existing page
- The user needs page interaction, layout, or state-flow optimization
- The user reports a page-level UI or behavior issue
- The user asks for landing pages, dashboards, detail pages, or workflow pages

## What This Skill Does

- Clarifies the page goal, audience, and primary action
- Designs page structure, content hierarchy, and interaction flow
- Implements or refines page UI with consistent styling
- Improves usability, readability, and conversion path
- Helps verify that page behavior matches the intended experience

## Workflow

1. Identify the page objective and core user action
2. Check existing templates, scripts, and style conventions before designing changes
3. Map key sections, state transitions, and visual priority
4. Implement or optimize the page using existing project patterns
5. Validate interaction flow, empty states, loading states, and data refresh behavior
6. Hand off a page result that is easy to review and iterate

## Project-Specific Guidance

- For homepage or chart pages, minimize footprint and move secondary controls into dialogs or drawers when possible
- For market/news/research pages, prioritize signal, timestamp, source, and actionability over decorative layout
- For asset-related pages, support quick filtering, bucketed evidence, and concise status tags
- For asynchronous actions, prefer visible progress states, polling feedback, retry affordances, and clear completion messages
- For financial dashboards, make dense information scannable with grouping, badges, hierarchy, and restrained color use

## Common Outputs

- New page implementation
- Existing page redesign
- Page interaction cleanup
- Layout and hierarchy optimization
- UX issue diagnosis
- Page review checklist

## Example Requests

- "帮我做一个首页"
- "优化这个页面的布局和交互"
- "修复详情页的展示问题"
- "做一个转化率更高的落地页"
