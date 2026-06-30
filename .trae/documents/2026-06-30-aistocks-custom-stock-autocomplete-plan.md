# `/serenity/aistocks` 新增股票自动索引计划

## Summary
- 目标：把 `/serenity/aistocks` 页面的“新增股票”从纯文本代码输入，升级为“参考主页搜索”的自动索引选择体验。
- 交互方向：参考主页 `code_search` 的搜索式选股体验，但不直接复用主页 `/tv/search`，继续使用当前轻量接口 `/serenity/aistocks/stock-search`。
- 提交流程：用户必须先从候选结果中点选股票，之后才能提交新增；不再允许仅靠手输任意代码直接提交。
- 数据范围：继续限定为 A 股，复用当前 `stock-search` 已支持的 `代码 / 名称 / 拼音首字母` 检索能力。

## Current State Analysis
- 当前新增股票表单位于 `web/chanlun_chart/cl_app/templates/serenity_aistocks_index.html` 的工具栏“新增股票”卡片中，核心控件为：
  - `#custom-stock-code-input`
  - `#custom-stock-theme-input`
  - `#custom-stock-submit-button`
  - `submitCustomStockForm()`
- 当前提交逻辑是纯文本方式：
  - 前端把 `code + theme_name` 直接 POST 到 `/serenity/aistocks/custom-stocks`
  - 后端在 `web/chanlun_chart/cl_app/serenity_aistocks.py` 中的 `serenity_aistocks_custom_stocks_add()` 再解析代码、校验 A 股并入库
- 当前页面已经有可复用的轻量搜索接口：
  - `GET /serenity/aistocks/stock-search`
  - 实现位于 `web/chanlun_chart/cl_app/serenity_aistocks.py` 的 `_search_serenity_aistocks_symbols()` 和 `serenity_aistocks_stock_search()`
  - 已支持 `query + exchange=a + limit`，匹配 `代码 / 名称 / 拼音首字母`
- 首页参考实现位于 `web/chanlun_chart/cl_app/templates/index.html`
  - 搜索入口是 `#code_search`
  - 交互上属于“输入后自动检索，再从候选里选中”的模式
- 仓库中仍保留全局 `/tv/search` 路由，定义在 `web/chanlun_chart/cl_app/__init__.py`
  - 但此前 `/serenity/aistocks` 已经刻意从 `/tv/search` 解耦，原因是避免触发 `__init__.py` 导入链上的向量库初始化副作用
  - 因此这次不应重新切回 `/tv/search`

## Assumptions & Decisions
- 自动索引只改“新增股票”流程，不改页面内已有的“搜索股票筛选”输入框。
- 搜索交互参考主页，但实现方式以当前页面技术栈为主，优先在现有原生 JS/CSS 基础上完成，不引入主页那套额外复杂控件依赖。
- 新增股票必须先点选候选；候选项选中后，将其规范化代码写入隐藏状态，并显示“名称 + 代码”的已选结果。
- 若用户修改输入内容导致已选候选失效，前端应清空已选状态并禁用提交按钮，避免“显示 A，提交 B”。
- 主题输入框与新增/删除、自定义主题逻辑保持不变，不在本次计划中扩展主题自动索引。
- 仍仅支持 A 股候选，因此前端自动索引请求固定传 `exchange=a`。

## Proposed Changes

### 1. 前端新增股票控件改为“搜索 + 选择”模式
**文件**
- `web/chanlun_chart/cl_app/templates/serenity_aistocks_index.html`

**变更**
- 保留现有“新增股票”卡片，但把 `#custom-stock-code-input` 的语义从“直接输入代码”改为“搜索股票”。
- 在该输入框下新增候选面板容器，例如：
  - `#custom-stock-suggestions`
  - `#custom-stock-selected-chip`
- 卡片内新增一个隐藏状态承载已选股票，例如：
  - `data-selected-symbol`
  - `data-selected-name`
  或隐藏 input，例如：
  - `#custom-stock-selected-symbol`
  - `#custom-stock-selected-name`
- 输入框占位文案改为明确搜索用途，如：
  - `输入代码 / 名称 / 拼音首字母`
- 提交按钮默认禁用，只有“已选股票 + 已填主题”同时满足时才启用。

**原因**
- 当前“代码输入框”过于原始，容易输错；改成“先搜再选”后，新增动作会更像主页的选股流程。

### 2. 自动索引前端状态流
**文件**
- `web/chanlun_chart/cl_app/templates/serenity_aistocks_index.html`

**变更**
- 新增前端函数，建议拆分为：
  - `debounceCustomStockSearch()`
  - `searchCustomStockCandidates(query)`
  - `renderCustomStockSuggestions(results)`
  - `selectCustomStockCandidate(item)`
  - `clearSelectedCustomStock()`
  - `updateCustomStockSubmitState()`
- 交互流程：
  1. 用户在“搜索股票”输入框中输入关键词
  2. 300ms 左右 debounce 后调用 `/serenity/aistocks/stock-search?query=...&exchange=a&limit=10`
  3. 渲染候选列表，候选文案显示：
     - 股票名称
     - 股票代码
     - 可选展示一个轻提示，如“拼音/名称/代码匹配”
  4. 用户点击某个候选后：
     - 输入框显示所选股票名称或“名称（代码）”
     - 记录规范化 symbol/code
     - 隐藏候选列表
     - 在输入框旁或下方显示已选标签
  5. 用户后续继续编辑输入框内容时：
     - 若内容不再对应已选结果，自动清空已选状态
     - 禁用提交按钮
- 键盘交互建议最小支持：
  - `ArrowDown / ArrowUp` 高亮候选
  - `Enter` 选中高亮项
  - `Escape` 关闭候选面板
- 点击页面其它区域时关闭候选面板。

**原因**
- 这是“参考主页搜索”的核心体验，但又不需要照搬主页整套控件库。

### 3. 继续复用轻量搜索接口，不回退到 `/tv/search`
**文件**
- `web/chanlun_chart/cl_app/serenity_aistocks.py`
- `web/chanlun_chart/cl_app/templates/serenity_aistocks_index.html`

**变更**
- 不新增新的后端搜索接口，继续使用现有：
  - `_search_serenity_aistocks_symbols()`
  - `serenity_aistocks_stock_search()`
- 如有必要，仅做轻微增强但不改变接口路径：
  - 保持返回体 `{ "results": [...] }`
  - 结果项继续包含：
    - `symbol`
    - `description`
    - `exchange`
- 前端新增股票的自动索引与名称点图的搜索逻辑，共享同一个 `STOCK_SEARCH_API_URL`。

**原因**
- 避免重新接回 `/tv/search`，从而再次引入之前已规避的向量库加载链路问题。

### 4. 自定义新增提交协议收紧为“基于已选候选”
**文件**
- `web/chanlun_chart/cl_app/templates/serenity_aistocks_index.html`
- `web/chanlun_chart/cl_app/serenity_aistocks.py`

**变更**
- 前端 `submitCustomStockForm()` 不再直接读取搜索输入框原始文本作为 code。
- 改为读取“已选候选”的规范化 symbol/code，再连同 `theme_name` 提交给：
  - `POST /serenity/aistocks/custom-stocks`
- 后端 `serenity_aistocks_custom_stocks_add()` 仍保留现有兜底校验：
  - 即使前端已点选，后端仍用 `_resolve_custom_stock_info_from_code()` 做最终校验
- 提示文案更新：
  - 未选中候选时返回/显示“请先从候选列表中选择股票”

**原因**
- 强制“选中后提交”，比“输入后提交”更符合用户需求，也能降低输错代码概率。

### 5. 模板样式与可用性微调
**文件**
- `web/chanlun_chart/cl_app/templates/serenity_aistocks_index.html`

**变更**
- 为新增股票卡片补一套搜索候选样式：
  - 下拉面板
  - hover / active 高亮
  - 已选标签 chip
  - loading / empty 状态
- 保持当前卡片式布局，不重做工具栏结构，只聚焦“新增股票”这一个子区域。
- 搜索候选面板宽度与当前新增股票表单对齐，避免遮挡技术扫描卡片。

**原因**
- 这是一次局部交互升级，不需要重新设计整页，只把“新增股票”做成更顺手的搜索式入口。

### 6. 测试覆盖
**文件**
- `test/test_serenity_aistocks.py`

**新增/调整测试**
- 模板层：
  - 断言“新增股票”卡片中存在候选列表容器
  - 断言存在“已选股票”状态容器/隐藏字段
  - 断言提交按钮初始为禁用态或依赖已选状态
  - 断言新增股票输入提示文案改为搜索式文案
- 接口契约层：
  - 继续验证 `/serenity/aistocks/stock-search` 支持中文和拼音首字母
  - 若增强返回结构，补对应断言
- 提交流程层：
  - 保留现有 `POST /serenity/aistocks/custom-stocks` 成功与失败测试
  - 新增“前端必须点选候选”的契约测试可体现在模板和脚本断言上，例如：
    - 存在 `selectCustomStockCandidate`
    - `submitCustomStockForm` 依赖 selected symbol，而非直接使用输入框文本

**原因**
- 这次主要是前端状态流变化，需要用模板/脚本断言锁住新交互契约。

## Verification Steps
1. 定向模板/交互测试
   - `PYTHONPATH=src:web/chanlun_chart pytest test/test_serenity_aistocks.py -k "custom_stock and stock_search" -q`
2. 全量页面回归
   - `PYTHONPATH=src:web/chanlun_chart pytest test/test_serenity_aistocks.py -q`
3. 诊断检查
   - `GetDiagnostics` 检查：
     - `web/chanlun_chart/cl_app/templates/serenity_aistocks_index.html`
     - `web/chanlun_chart/cl_app/serenity_aistocks.py`
     - `test/test_serenity_aistocks.py`
4. 手工验收
   - 在“新增股票”输入框中输入：
     - 中文，如 `德福`
     - 代码，如 `301511`
     - 拼音首字母，如 `dfkj`
   - 验证候选面板会出现
   - 选中候选后，验证提交按钮可用
   - 不选候选仅手输文本时，验证无法提交
   - 新增成功后跳转到目标主题页，且主题/行显示正常

