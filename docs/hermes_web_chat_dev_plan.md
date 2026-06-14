# Hermes Web Chat Development Plan

## 1. 目标

本计划用于落地以下能力：

- 多用户 Web Chat
- 每个用户独立会话、独立结果、独立历史记录
- Hermes 作为聊天编排层、记忆层、调度层
- chanlun-pro 作为市场分析引擎
- 支持主题推演、市场数据查看、历史分析、跨资产佐证
- 后续可扩展到附件上传、订阅推送、Telegram 等入口

## 2. 当前现状

当前项目已经具备基础聊天雏形：

- 已有聊天页面 `web/chanlun_chart/cl_app/templates/ai_chat.html`
- 已有聊天接口 `web/chanlun_chart/cl_app/ai_agent/chat_api.py`
- 已有市场研究主能力 `web/chanlun_chart/cl_app/news_vector_api.py`

当前不足：

- 仍偏单用户登录态
- 会话历史只保存在前端内存中
- 没有真正的 `tenant_id / user_id / session_id` 模型
- Hermes 还没有接入 chanlun-pro 的服务化 API

## 3. Skill 安装建议

结论先说：

- 没有一个单独的 skill 能一次性包办全部设计和开发
- 最优做法是安装一组互补 skills，让我在不同阶段切换使用
- 其中有些 skill 是核心必装，有些是增强项

### 3.1 核心必装

1. `meta-dispatcher-task-orchestrator`
   - 作用：拆解复杂任务，管理多模块依赖
   - 用途：适合当前这种 Web Chat + Hermes + chanlun-pro + 多用户会话的跨模块工程

2. `universal-dev-team`
   - 作用：端到端推进需求到交付
   - 用途：适合后续直接按计划逐阶段开发

3. `backend-python-expert`
   - 作用：强化 Python 后端、API、异步任务、架构设计
   - 用途：适合 Flask 侧 service API、Hermes 对接、数据模型落库

4. `api-design-principles`
   - 作用：规范 API 契约与接口一致性
   - 用途：适合设计 Hermes <-> chanlun-pro service API、前后端消息协议

5. `page-agent`
   - 作用：搭建和优化页面级交互
   - 用途：适合现有 `ai_chat.html` 的会话化升级

6. `webapp-testing`
   - 作用：浏览器联调、交互验证、截图、日志检查
   - 用途：适合验证 Web Chat 流式输出、历史会话恢复、右侧证据面板

7. `quality-gate`
   - 作用：交付前统一做质量检查
   - 用途：适合每完成一个阶段后做回归收口

### 3.2 强烈推荐

1. `repo-onboarding`
   - 用途：后续进入 Hermes 仓库某个新模块时快速梳理结构

2. `security-specialist`
   - 用途：多用户登录、服务鉴权、会话隔离、权限边界

3. `frontend-design`
   - 用途：如果后续要把 Web Chat 做成更成熟的研究工作台 UI

4. `git-workflow`
   - 用途：阶段性交付时整理 commit、PR、变更边界

### 3.3 可选增强

1. `github-search-discovery`
   - 用途：需要找 Hermes / chat / multi-tenant / streaming 的外部参考实现时使用

2. `github`
   - 用途：后续如果要同步 GitHub issue / PR / 设计草案

### 3.4 当前项目已装的 skills

项目本地目录 `.trae/skills/` 中当前已有：

- `github`
- `page-agent`

这意味着当前仓库已经具备：

- GitHub 辅助能力
- 页面级实现能力

但还缺少本次开发最关键的：

- `meta-dispatcher-task-orchestrator`
- `universal-dev-team`
- `backend-python-expert`
- `api-design-principles`
- `webapp-testing`
- `quality-gate`
- `security-specialist`

### 3.5 最小可用安装组合

如果你只想先装一批最有价值的，推荐最小组合如下：

- `meta-dispatcher-task-orchestrator`
- `universal-dev-team`
- `backend-python-expert`
- `api-design-principles`
- `page-agent`
- `webapp-testing`
- `quality-gate`

如果你想把多用户和服务安全一起做稳，再加：

- `security-specialist`

## 4. 推荐执行方式

后续开发时，建议按下面方式使用 skills：

1. 设计阶段
   - `meta-dispatcher-task-orchestrator`
   - `api-design-principles`
   - `backend-python-expert`

2. 后端开发阶段
   - `universal-dev-team`
   - `backend-python-expert`
   - `security-specialist`

3. 前端开发阶段
   - `page-agent`
   - `frontend-design`

4. 联调与回归阶段
   - `webapp-testing`
   - `quality-gate`

## 5. 分阶段开发计划

### 阶段 0：需求冻结

目标：

- 明确第一版只做 Web Chat
- 明确第一版优先支持个人多会话
- 明确 Hermes 只做编排，chanlun-pro 只做分析

产出：

- 最终范围清单
- API 清单
- 页面清单

### 阶段 1：chanlun-pro 服务化改造

目标：

- 将现有分析能力改造成供 Hermes 调用的 service API

重点：

- 增加 service auth
- 传递 `tenant_id / user_id / session_id / trace_id`
- 将页面登录态接口与服务接口解耦

建议接口：

- `POST /api/service/theme_simulation`
- `POST /api/service/market_data/view`
- `POST /api/service/market_data/sync`
- `POST /api/service/historical_analysis`

### 阶段 2：Hermes Skills 接入

目标：

- 让 Hermes 成为 Web Chat 的编排层

建议 skills：

- `chanlun-theme-analysis`
- `chanlun-market-view`
- `chanlun-market-sync`
- `chanlun-historical-analysis`

能力边界：

- Hermes 负责理解用户问题和路由
- chanlun-pro 负责返回结构化分析结果

### 阶段 3：多用户会话模型

目标：

- 落地独立用户、独立会话、独立消息存储

建议数据表：

- `tenants`
- `users`
- `chat_sessions`
- `chat_messages`
- `chat_attachments`
- `analysis_requests`
- `subscriptions`
- `audit_logs`

### 阶段 4：Web Chat 页面升级

目标：

- 在现有 `ai_chat.html` 基础上升级为真正的会话工作台

重点：

- 左侧真实会话列表
- 中间消息历史恢复
- 右侧证据与结构化结果面板
- 输入区支持上下文和附件

### 阶段 5：统一消息协议

目标：

- 统一前后端消息结构，降低后续维护成本

建议消息类型：

- `user_text`
- `assistant_text`
- `tool_status`
- `tool_result`
- `citation`
- `analysis_summary`
- `chart`
- `error`

### 阶段 6：附件与证据接入

目标：

- 支持 PDF、Word、Excel、Markdown、Text 上传
- 将上传材料纳入会话级证据

### 阶段 7：自动化与推送

目标：

- 用户可订阅主题和资产
- Hermes 定时推送简报和提醒

### 阶段 8：联调与质量收口

目标：

- 接口测试
- 会话隔离测试
- 页面联调测试
- 流式输出与异常处理验证

## 6. MVP 验收标准

第一版上线前至少满足：

- 多个用户可同时登录
- 每个用户可创建多个独立会话
- 每个会话可恢复消息历史
- Hermes 可稳定调用 chanlun-pro 的 service API
- 聊天页可展示文本回答、引用、结构化分析结果
- 不同用户和不同会话之间不会串数据

## 7. 推荐的实际开发顺序

建议后续按以下顺序让我继续开发：

1. 先做 API 契约和数据库表设计
2. 再做 chanlun-pro service API
3. 再做 Hermes skills
4. 再做 Web Chat 会话页面
5. 再做附件与推送
6. 最后做联调与回归

## 8. 第 1 阶段详细设计

本节用于指导下一步实际编码，重点覆盖：

- chanlun-pro 的 service API 契约
- Web Chat 会话接口
- 数据表设计
- 前后端消息协议

### 8.1 设计原则

1. 页面接口与服务接口分离
   - 浏览器页面继续使用现有登录态接口
   - Hermes 只调用 service API

2. 鉴权与业务上下文分离
   - 鉴权依赖服务 token
   - 业务隔离依赖 `tenant_id / user_id / session_id`

3. 结构化结果优先
   - chanlun-pro 返回结构化 payload
   - Hermes 负责将结构化结果转成聊天回答

4. 聊天流和分析流统一消息协议
   - 文本回答、引用、工具状态、图表、结构化分析都统一走事件流

### 8.2 chanlun-pro Service API 契约

推荐统一前缀：

- `/api/service`

统一请求头：

- `Authorization: Bearer <service_token>`
- `X-Tenant-Id: <tenant_id>`
- `X-User-Id: <user_id>`
- `X-Session-Id: <session_id>`
- `X-Trace-Id: <trace_id>`
- `X-Request-Source: hermes-web-chat`

统一成功响应结构：

```json
{
  "success": true,
  "trace_id": "trc_xxx",
  "session_id": "sess_xxx",
  "data": {},
  "meta": {}
}
```

统一错误响应结构：

```json
{
  "success": false,
  "trace_id": "trc_xxx",
  "error": {
    "code": "INVALID_ARGUMENT",
    "message": "theme_id is required",
    "details": {}
  }
}
```

建议错误码：

- `UNAUTHORIZED`
- `FORBIDDEN`
- `INVALID_ARGUMENT`
- `NOT_FOUND`
- `RATE_LIMITED`
- `UPSTREAM_ERROR`
- `INTERNAL_ERROR`

#### A. 主题推演

- `POST /api/service/theme_simulation`

请求体建议：

```json
{
  "market": "fx",
  "code": "AUDUSD",
  "theme_id": "aud_rba_policy",
  "theme_text": "澳元、联储、商品与风险偏好",
  "analysis_mode": "deep_research",
  "attachments": [
    {
      "attachment_id": "att_xxx",
      "name": "rba_note.pdf"
    }
  ],
  "options": {
    "include_multi_agent": true,
    "include_cross_asset": true,
    "include_market_snapshot": true
  }
}
```

响应体建议：

```json
{
  "success": true,
  "trace_id": "trc_xxx",
  "session_id": "sess_xxx",
  "data": {
    "analysis_type": "theme_simulation",
    "summary": "澳元下跌的主线来自...",
    "report": {},
    "research_agent": {},
    "comprehensive_reasoning": {},
    "citations": [],
    "charts": []
  },
  "meta": {
    "latency_ms": 1820
  }
}
```

#### B. 市场数据查看

- `POST /api/service/market_data/view`

请求体建议：

```json
{
  "market": "fx",
  "code": "AUDUSD",
  "view_type": "snapshot",
  "fields": [
    "price",
    "returns_24h",
    "macro_events",
    "cross_asset_watch"
  ]
}
```

#### C. 市场数据同步

- `POST /api/service/market_data/sync`

请求体建议：

```json
{
  "market": "fx",
  "code": "AUDUSD",
  "sync_scope": [
    "calendar",
    "cftc",
    "price_bars",
    "cross_asset_watch"
  ],
  "force_refresh": false
}
```

#### D. 历史分析

- `POST /api/service/historical_analysis`

请求体建议：

```json
{
  "market": "fx",
  "code": "AUDUSD",
  "start_time": "2026-04-01T00:00:00Z",
  "end_time": "2026-04-10T00:00:00Z",
  "analysis_mode": "event_price_review",
  "window_config": {
    "lookback_minutes": 360,
    "lookforward_minutes": 360
  }
}
```

### 8.3 Web Chat 会话接口契约

Web 前端建议对 Hermes 暴露以下接口：

#### A. 创建会话

- `POST /api/chat/sessions`

请求体：

```json
{
  "title": "澳元主题研究",
  "context_market": "fx",
  "context_code": "AUDUSD",
  "context_theme": "aud_rba_policy"
}
```

#### B. 会话列表

- `GET /api/chat/sessions`

支持查询参数：

- `status`
- `market`
- `limit`
- `cursor`

#### C. 会话详情

- `GET /api/chat/sessions/{session_id}`

返回：

- 会话元信息
- 最近消息
- 当前上下文
- 最近一次分析摘要

#### D. 发送消息

- `POST /api/chat/sessions/{session_id}/messages`

请求体：

```json
{
  "message": {
    "type": "user_text",
    "content": "澳元为什么跌，是否已经定价完毕？"
  },
  "context": {
    "market": "fx",
    "code": "AUDUSD"
  },
  "options": {
    "mode": "deep_research",
    "stream": true
  }
}
```

#### E. 流式响应

- `GET /api/chat/sessions/{session_id}/stream`

事件流建议类型：

- `message.delta`
- `message.completed`
- `tool.started`
- `tool.completed`
- `citation.created`
- `analysis.created`
- `error`

### 8.4 数据表设计

以下为 MVP 必要表结构。

#### A. `tenants`

字段建议：

- `id`
- `name`
- `status`
- `plan_code`
- `created_at`
- `updated_at`

#### B. `users`

字段建议：

- `id`
- `tenant_id`
- `username`
- `display_name`
- `email`
- `password_hash`
- `status`
- `last_login_at`
- `created_at`
- `updated_at`

#### C. `chat_sessions`

字段建议：

- `id`
- `tenant_id`
- `user_id`
- `title`
- `context_market`
- `context_code`
- `context_theme`
- `status`
- `last_message_at`
- `created_at`
- `updated_at`

用途：

- 存储会话级上下文
- 支持左侧历史会话列表

#### D. `chat_messages`

字段建议：

- `id`
- `tenant_id`
- `user_id`
- `session_id`
- `role`
- `message_type`
- `content`
- `structured_payload`
- `tool_name`
- `trace_id`
- `created_at`

用途：

- 存储用户消息、助手消息、工具消息、结构化分析结果

#### E. `chat_attachments`

字段建议：

- `id`
- `tenant_id`
- `user_id`
- `session_id`
- `file_name`
- `file_type`
- `storage_path`
- `parse_status`
- `parsed_text`
- `created_at`

#### F. `analysis_requests`

字段建议：

- `id`
- `tenant_id`
- `user_id`
- `session_id`
- `request_type`
- `request_payload`
- `response_payload`
- `status`
- `latency_ms`
- `created_at`

用途：

- 存储每次 Hermes 调 chanlun-pro 的请求与响应摘要

#### G. `subscriptions`

字段建议：

- `id`
- `tenant_id`
- `user_id`
- `subscription_type`
- `target_market`
- `target_code`
- `target_theme`
- `schedule_expr`
- `status`
- `created_at`

#### H. `audit_logs`

字段建议：

- `id`
- `tenant_id`
- `user_id`
- `session_id`
- `action`
- `resource_type`
- `resource_id`
- `trace_id`
- `payload`
- `created_at`

### 8.5 前后端消息 Schema

推荐统一消息对象：

```json
{
  "id": "msg_xxx",
  "session_id": "sess_xxx",
  "role": "assistant",
  "message_type": "analysis_summary",
  "content": "澳元短线走弱主要来自...",
  "structured_payload": {
    "summary": "澳元短线走弱",
    "comprehensive_reasoning": {},
    "citations": []
  },
  "created_at": "2026-04-11T10:00:00Z"
}
```

建议的 `message_type`：

- `user_text`
- `assistant_text`
- `tool_status`
- `tool_result`
- `citation`
- `analysis_summary`
- `chart`
- `error`

### 8.6 与现有代码的映射关系

第一阶段实际开发时，优先改造以下文件：

- `web/chanlun_chart/cl_app/news_vector_api.py`
  - 增加 service API 路由
  - 抽取页面接口与服务接口共用的分析逻辑

- `web/chanlun_chart/cl_app/ai_agent/chat_api.py`
  - 由“直接调用本地 AGIAgent”
  - 逐步演进为“调用 Hermes 或兼容双模式”

- `web/chanlun_chart/cl_app/templates/ai_chat.html`
  - 从前端内存消息历史
  - 升级为真实 session 驱动

### 8.7 第 1 阶段验收标准

完成本阶段设计后，应满足：

- API 请求头、鉴权、错误结构已明确
- Web Chat 会话接口已明确
- 关键数据表已明确
- 聊天消息 schema 已明确
- 已能直接进入后端落代码阶段

## 9. 结论

如果你的目标是“让我尽量独立地把这套功能设计并开发完整”，推荐安装组合是：

- `meta-dispatcher-task-orchestrator`
- `universal-dev-team`
- `backend-python-expert`
- `api-design-principles`
- `page-agent`
- `webapp-testing`
- `quality-gate`
- `security-specialist`

其中：

- 前 7 个是主力组合
- `security-specialist` 是多用户场景下的强增强项

后续如果你让我正式开工，最佳起点是：

- 第一步：API 契约草案
- 第二步：数据库表结构
- 第三步：chanlun-pro 服务化改造
