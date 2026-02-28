# AGI 专业市场助手 (AGI Market Intelligence) - 系统设计方案

## 1. 项目愿景 (Vision)
打造一个**机构级、专业、可扩展**的金融市场 AI 助手。它不仅是一个聊天机器人，更是一个集成了实时行情、多维知识库（新闻、产品、研报）的智能投研参谋。

**核心特征**:
*   **可扩展性 (Extensible)**: 知识库和 Agent 能力插件化，随需扩展。
*   **配置化 (Configurable)**: 核心数据（如产品逻辑）支持前端录入，非硬编码。
*   **专业性 (Professional)**: 界面简洁、数据严谨、引用可溯源。

---

## 2. 系统架构 (System Architecture)

系统采用 **Router-Agent-Tool** 架构，实现高度解耦。

### 2.1 后端架构 (Backend)

#### A. 核心层 (Core Layer)
1.  **Agent Orchestrator (编排器)**
    *   **职责**: 接收用户 Query，管理对话上下文，调用 LLM 进行意图识别和工具分发。
    *   **机制**: 基于 LLM Function Calling (Tool Use) 自动路由。
    *   **扩展性**: 维护一个 `ToolRegistry`，新增能力只需注册即可。

2.  **知识库引擎 (Knowledge Engine)**
    *   **BaseVectorDB (基类)**: 定义标准接口 `search(query, top_k)`, `add(doc)`, `update(id, doc)`, `delete(id)`。
    *   **NewsVectorDB (实现)**: 现有的新闻向量库，支持时间过滤、来源过滤。
    *   **ProductVectorDB (实现)**: **新增**，存储产品/标的的多维属性（基本面逻辑、代码、分类）。
    *   **Storage**: 继续使用 **ChromaDB** 作为向量存储，**SQLite/MySQL** 存储结构化元数据（如产品详情）。

#### B. 服务层 (Service Layer)
1.  **Chat Service**: 处理 `/api/ai/chat` 请求，封装 SSE 流式响应，管理会话状态。
2.  **Knowledge Service**: 提供 `/api/knowledge/*` 接口，支持前端对知识库的 CRUD 操作。

### 2.2 前端架构 (Frontend)

#### A. 界面设计 (UI/UX) - "Institutional Style"
1.  **配色**: 深空灰/黑背景，金融蓝 (#007AFF) 或金色 (#D4AF37) 作为强调色。字体选用系统等宽字体或无衬线字体 (Inter/Roboto)。
2.  **布局**: **双栏布局 (Two-Pane)**。
    *   **Left Pane (Chat)**: 对话流。消息气泡极简设计，引用处高亮并带角标 `[1]`。
    *   **Right Pane (Context)**: **动态上下文面板**。
        *   当 AI 提到 "黄金" -> 右侧自动展示黄金实时行情、关键属性卡片。
        *   当 AI 引用 "新闻" -> 右侧展示新闻列表和摘要。
        *   支持折叠/展开，保持界面清爽。

#### B. 交互逻辑
1.  **流式渲染**: 使用 `EventSource` 或 `fetch` 流式读取，配合 Markdown 渲染库实现打字机效果。
2.  **数据可视化**: 识别文本中的代码/数据，自动渲染为 Sparkline (迷你图) 或表格。

---

## 3. 详细模块设计 (Detailed Design)

### 3.1 数据库设计 (Database Schema)

#### A. 向量库 (ChromaDB)
*   **Collection**: `product_knowledge`
    *   `id`: `symbol` (e.g., "CL")
    *   `document`: 自然语言描述 (e.g., "原油(CL)是能源类核心资产，受OPEC产量和地缘政治影响...")
    *   `metadata`:
        *   `name_cn`: "原油"
        *   `category`: "energy"
        *   `exchange`: "NYMEX"
        *   `bullish_logic`: "通胀预期，供应短缺" (用于检索)
        *   `bearish_logic`: "经济衰退，美元走强" (用于检索)

#### B. 结构化存储 (MySQL/SQLite - 现有 `chanlun` DB)
*   **Table**: `cl_product_knowledge` (新增)
    *   用于前端管理界面的数据回显和编辑。
    *   字段: `id`, `symbol`, `name`, `desc`, `tags`, `updated_at`.

### 3.2 API 接口设计 (API Specification)

#### A. 聊天接口
*   `POST /api/ai/chat`
    *   **Input**: `{ "messages": [...], "model": "gpt-4" }`
    *   **Output**: SSE Stream
        *   `event: tool_start` (正在检索产品库...)
        *   `event: tool_result` (检索到: 黄金, 原油) -> **触发前端右侧面板更新**
        *   `event: text_delta` (回答文本...)
        *   `event: finish`

#### B. 知识库管理接口
*   `GET /api/knowledge/products` (列表)
*   `POST /api/knowledge/product` (新增/更新 - 同步写入 SQL 和 VectorDB)
*   `DELETE /api/knowledge/product/<symbol>` (删除)

### 3.3 扩展性设计 (Extensibility)

*   **如何增加新 Agent?**
    *   只需在 `cl_app/ai_agent/tools/` 下新建一个 `Tool` 类 (如 `ReportSearchTool`)。
    *   在 `AgentOrchestrator` 初始化时注册即可。LLM 会自动感知并使用。

---

## 4. 开发实施计划 (Implementation Roadmap)

### Phase 1: 核心重构与数据基座 (Backend Foundation)
*   [ ] **Task 1.1**: 封装 `ProductVectorDB`，实现数据的增删改查接口。
*   [ ] **Task 1.2**: 开发 `Knowledge API`，支持通过 API 录入产品数据。
*   [ ] **Task 1.3**: 编写初始化脚本，将现有 `futures_commodity_mapping.py` 数据导入新库作为冷启动数据。

### Phase 2: Agent 编排 (Agent Logic)
*   [ ] **Task 2.1**: 实现 `AgentOrchestrator`，集成 LLM (OpenAI/Compatible) 的 Tool Calling。
*   [ ] **Task 2.2**: 注册 `NewsTool` 和 `ProductTool`。
*   [ ] **Task 2.3**: 开发 SSE 流式响应处理逻辑，确保能区分 "文本" 和 "工具数据"。

### Phase 3: 前端管理后台 (Admin UI)
*   [ ] **Task 3.1**: 在设置页或新页面增加 "知识库管理" 模块。
*   [ ] **Task 3.2**: 实现产品录入表单 (支持自动生成 Embedding 预览)。

### Phase 4: 专业聊天界面 (Chat UI)
*   [ ] **Task 4.1**: 开发 `ai_chat.html`，实现双栏布局。
*   [ ] **Task 4.2**: 联调 SSE 接口，实现流式对话 + 右侧 Context 面板联动。

---

## 5. 风险与对策 (Risks & Mitigation)

*   **Risk**: LLM 意图识别不准，胡乱调用工具。
    *   **Fix**: 优化 System Prompt，增加 Few-Shot Examples (少样本示例) 引导。
*   **Risk**: 向量检索结果不相关。
    *   **Fix**: 引入 Rerank (重排序) 步骤，对 Top-K 结果进行二次打分。
*   **Risk**: 响应延迟过高。
    *   **Fix**: 并行执行工具调用 (如果涉及多个)；对常见问题做缓存。
