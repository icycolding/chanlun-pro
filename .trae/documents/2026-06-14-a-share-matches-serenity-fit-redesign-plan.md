# A股映射全主题 Serenity Fit 重构计划

## Summary

本次改造目标是把 `a_share_matches` 从“静态 A 股映射展示页”升级成“按 Serenity 方法论组织的研究页”：

- 对所有主题进行全量重写，而不是只调整局部文案
- 将当前写死在模板中的主题/项目股/A股映射数据抽成结构化数据
- A股映射区改成 `主映射` + `候选池` 两层
- 每张 A 股卡片展示 `Serenity Fit 数值 + 等级`，并补齐完整 6 字段
- 保留并兼容现有的项目股行情、A股行情、Tweets 摘要、详情页与自动刷新逻辑

## Current State Analysis

### 当前入口与后端

- `web/chanlun_chart/cl_app/__init__.py`
  - 已存在 `/a_share_matches` 页面路由
  - 已存在 `/a_share_matches/project_ticks` 项目股票行情接口
  - 已存在 `/a_share_matches/tweet_summaries` 和 `/a_share_matches/tweets/<symbol>/data`，用于 Tweets 摘要和详情自动刷新
- 当前后端对页面主体内容没有提供结构化上下文，页面核心研究内容直接写在模板中

### 当前页面实现

- `web/chanlun_chart/cl_app/templates/a_share_matches.html`
  - 样式、主题内容、项目股票卡片、A股映射卡片都集中在一个模板中
  - 主题与卡片内容基本以内联 HTML 写死在模板正文里
  - A股映射当前展示形式仍是旧模型：
    - `match-heading`
    - `match-role`
    - `匹配强度 / 上游程度 / Serenity相似度` 三个标签
  - 前端已存在以下可复用逻辑：
    - A股行情加载 `loadAShareMatchQuotes()`
    - 项目股行情加载 `loadProjectStockQuotes()`
    - Tweets 摘要加载与每小时刷新 `loadProjectTweetSummaries()` / `refreshProjectTweetSummariesIfNeeded()`

### 当前问题

- 页面研究框架仍偏“题材映射”，不够 Serenity 化
- 主题数据写死在大段 HTML 中，难以全量重排、复核和维护
- A股卡片信息密度不够，无法明确区分：
  - 哪些是 `主映射`
  - 哪些只是 `候选池`
  - 哪些更像 `上游 choke point`
  - 哪些只是 `受益层`
- 现有标签不可比较、不可复核，不利于后续持续迭代

## Proposed Changes

### 1. 新增结构化研究数据模块

#### 文件

- 新增 `web/chanlun_chart/cl_app/a_share_matches_catalog.py`

#### 改动内容

- 将当前模板里硬编码的所有主题数据，抽成结构化 Python 数据
- 顶层结构按 `themes -> project_stocks -> main_matches / candidate_matches` 组织
- 每只项目股至少包含：
  - `symbol`
  - `display_name`
  - `company_name`
  - `exchange`
  - `market`
  - `theme_chip`
  - `research_summary`
- 每只 A 股卡片至少包含：
  - `code`
  - `name`
  - `role`
  - `serenity_fit_score`
  - `serenity_fit_level`
  - `supply_chain_position`
  - `mapping_path`
  - `judgement`
  - `major_risk`

#### 设计决定

- `Serenity Fit` 使用 `20 分制数值 + 等级`
- 所有主题全量改写，不保留旧的 `匹配强度 / 上游程度 / Serenity相似度` 标签作为主展示
- A股映射统一拆成：
  - `主映射`
  - `候选池`

### 2. 让页面由结构化数据驱动渲染

#### 文件

- 修改 `web/chanlun_chart/cl_app/__init__.py`
- 修改 `web/chanlun_chart/cl_app/templates/a_share_matches.html`

#### 改动内容

- 在 `/a_share_matches` 路由中引入结构化数据模块，并把主题数据传给模板
- 模板从“静态写死 section/card”改为“循环渲染 themes / stock cards / A股卡片”
- 保留页面现有 hero、行情区、Tweets 摘要区的总体布局，但重构 A股映射区 DOM

#### 目标 DOM 结构

- 每个主题 section 显示：
  - 主题标题
  - 项目股数量
- 每个项目股票卡片显示：
  - 项目股票头部信息
  - 项目股票基础元信息
  - 项目股行情区
  - Serenity Tweets 摘要区
  - 项目股票研究判断区
  - `主映射` A股区
  - `候选池` A股区
- 每个 A 股卡片默认展示完整 6 字段：
  - `Serenity Fit（数值 + 等级）`
  - `供应链位置`
  - `映射路径`
  - `一句话判断`
  - `主要风险`
  - `行情区`

### 3. 重做所有主题的研究文案与分层

#### 文件

- 主要落在 `web/chanlun_chart/cl_app/a_share_matches_catalog.py`

#### 改动内容

- 对所有主题下的项目股票与 A 股映射执行全量文案重写
- 以 Serenity 方法论重标每张卡片：
  - 优先区分 `上游核心器件 / 材料 / 工艺 / 设备 / 模组 / 受益层`
  - 重新决定哪些 A 股进入 `主映射`
  - 重新决定哪些 A 股降为 `候选池`
- 每张 A 股卡片产出标准化研究文案：
  - `Serenity Fit 数值`
  - `Serenity Fit 等级`
  - `供应链位置`
  - `映射路径`
  - `一句话判断`
  - `主要风险`

#### 执行原则

- 同赛道不等于高 Serenity Fit
- 先判断是否属于上游 choke point，再判断是否同主题
- 主映射优先选择：
  - 更上游
  - 更稀缺
  - 认证/替代壁垒更高
  - 更符合 Serenity 叙事
- 候选池承接：
  - 关键受益
  - 中游配套
  - 主题相关但非最核心 choke point

### 4. 重构样式与交互，但保留现有数据能力

#### 文件

- 修改 `web/chanlun_chart/cl_app/templates/a_share_matches.html`

#### 改动内容

- 为新结构新增样式：
  - 主映射/候选池分组标题
  - `Serenity Fit` 分数与等级徽标
  - 新版研究字段网格
  - 更适合长文案的卡片布局
- 调整前端 JS 选择器，确保以下能力继续工作：
  - A股行情请求仍能识别每张 A 股卡片的证券代码
  - 项目股行情仍能识别每张项目股票卡片的 symbol / exchange / market / company_name / display_name
  - Tweets 摘要仍能在所有项目股票卡片上正确挂载
  - 每小时 Tweets 自动刷新逻辑保持可用
- 现有左侧主题导航如已存在，需要同步适配新的 section 标识和标题结构

### 5. 增加针对结构化数据和页面渲染的测试

#### 文件

- 新增 `test/test_a_share_matches_catalog.py`
- 视实现情况补充 `test/test_a_share_matches_page.py` 或在现有测试文件中补断言

#### 测试内容

- 结构化数据完整性：
  - 每个主题都有标题与项目股列表
  - 每只项目股都有 `main_matches` 和 `candidate_matches`
  - 每张 A 股卡片包含约定字段
- 分数展示数据合法性：
  - `serenity_fit_score` 在允许范围内
  - `serenity_fit_level` 与分数区间一致
- 页面渲染关键断言：
  - 页面能输出 `主映射` 和 `候选池`
  - 新字段能渲染到 HTML
  - 现有行情 / Tweets 相关 DOM 钩子仍存在

## Assumptions & Decisions

### 已确认决策

- 改造深度：`全量重写研究文案`
- 页面实现方式：`抽成结构化数据`
- A股展示层级：`分主映射 / 候选池`
- Serenity Fit 展示：`数值 + 等级`
- A股卡片字段：`完整 6 字段`

### 实现假设

- 当前 `a_share_matches` 的所有主题原始内容均可从现有模板中迁移出来，不依赖额外隐藏数据源
- 本次优先改 `a_share_matches.html` 页面；Tweets 详情页 `a_share_match_tweets.html` 不需要跟随做信息架构重构
- 行情与 Tweets 摘要接口无需新增业务能力，只需要适配新的 DOM 结构和数据属性

### 不在本次范围

- 不扩展新的行情市场支持
- 不改 Serenity tweets 的匹配算法
- 不引入数据库或 CMS
- 不把研究文案自动生成为 AI 在线推理流程，本次仍以代码内维护的数据为准

## Verification Steps

### 代码与渲染验证

- 检查 `/a_share_matches` 页面能正常渲染所有主题
- 检查每个主题都显示：
  - 项目股卡片
  - 主映射
  - 候选池
- 检查每张 A 股卡片都显示：
  - `Serenity Fit 分数`
  - `Serenity Fit 等级`
  - `供应链位置`
  - `映射路径`
  - `一句话判断`
  - `主要风险`

### 功能回归验证

- 验证项目股行情仍正常显示
- 验证 A股行情仍正常显示
- 验证 Tweets 摘要仍可加载
- 验证 Tweets 自动刷新逻辑未被新 DOM 结构破坏
- 验证主题导航锚点仍可跳转

### 测试与诊断

- 运行相关 pytest：
  - 新增 catalog 测试
  - 现有 `test/test_a_share_matches_tweets.py`
  - 现有 `test/test_a_share_matches_quotes.py`
- 对改动文件运行诊断，确保没有新语法/模板错误

## Implementation Order

1. 提取并重建全量主题结构化数据
2. 修改 `/a_share_matches` 路由，向模板传递 catalog
3. 重写 `a_share_matches.html` 的主题与卡片渲染结构
4. 适配前端 JS 的 DOM 选择器与挂载点
5. 补充 catalog/页面测试
6. 运行测试与诊断，修复回归问题
