# Serenity AI Stocks 价格入库与读库方案

## Summary

- 目标：把 `serenity-aleabitoreddit-main/aistocks.xlsx` 网页里的价格展示，从“页面打开后实时直连行情源抓取”，改成“后端每 1 分钟定时抓价保存到当前项目数据库，页面加载时直接从数据库读取最新价”。
- 范围：仅覆盖 `Serenity AI Stocks` 页面价格链路，不改 Excel 解析逻辑，不引入新数据库，不切换当前项目的 ORM/配置体系。
- 已锁定决策：
  - 使用当前项目数据库：`src/chanlun/db.py` 的 `DB` 单例，对应默认 `sqlite` 的 `~/.chanlun_pro/db/chanlun_klines.sqlite`
  - 存储模式：`最新价覆盖`
  - 定时频率：`1 分钟`

## Current State Analysis

### 现有页面链路

- 文件：`web/chanlun_chart/cl_app/serenity_aistocks.py`
- 当前 workbook 来自固定路径：
  - `serenity-aleabitoreddit-main/aistocks.xlsx`
- 当前每个 sheet 的行数据是在 `_build_sheet_rows()` 中生成，初始价格字段是：
  - `price_text = "--"`
  - `rate_text = "--"`
  - `price_status = "pending"` 或 `unsupported`
- 当前价格获取方式：
  - 页面打开后，前端调用 `POST /serenity/aistocks/prices`
  - 路由内部执行 `fetch_serenity_aistocks_prices(items)`
  - 该函数直接调用：
    - `get_exchange(Market(...))`
    - `fetch_tick_snapshots(...)`
  - 也就是说当前是前端触发、后端实时连行情源，并没有价格入库

### 现有数据库能力

- 文件：`src/chanlun/config.py`
  - 默认配置为 `DB_TYPE = "sqlite"`
  - 默认库名为 `chanlun_klines`
- 文件：`src/chanlun/db.py`
  - `DB` 是项目主关系库单例
  - `DB.__init__()` 里已经通过 `Base.metadata.create_all(self.engine)` 自动建表
  - 现有表命名风格统一使用 `cl_*`
  - 已存在典型 insert/query 模式，例如：
    - `news_insert(...)`
    - `news_query(...)`
  - 说明最适合按现有风格新增一张价格表和对应查询/覆盖更新方法

### 现有调度能力

- 文件：`web/chanlun_chart/cl_app/__init__.py`
- 当前应用已经有 scheduler 任务挂载模式，典型例子是：
  - `_run_jin10_watch_job(...)`
  - `_start_jin10_watch(...)`
  - `scheduler.add_job(... trigger="interval", seconds=interval, replace_existing=True, coalesce=True, max_instances=1 ...)`
- 这意味着可以直接复用相同模式，为 `Serenity AI Stocks` 增加一个“定时抓价并入库”的后台任务

## Proposed Changes

### 1. 在主数据库新增 Serenity AI Stocks 最新价表

- 文件：`src/chanlun/db.py`
- 新增表模型：
  - 建议表名：`cl_serenity_aistocks_latest_price`
- 表字段建议：
  - `id`: 自增主键
  - `market`: 市场，取值如 `a` / `hk` / `us`
  - `code`: 规范化后的代码，如 `SH.600183` / `09926` / `NVDA`
  - `symbol`: 原展示 symbol，便于调试和页面映射
  - `price`: 最新价，`Float`
  - `rate`: 涨跌幅原始值，`Float`
  - `price_text`: 格式化后的价格文本，直接供页面展示
  - `rate_text`: 格式化后的涨跌幅文本，直接供页面展示
  - `status`: `ok` / `unsupported` / `error`
  - `source`: 数据来源标记，固定写当前抓价链路来源
  - `fetched_at`: 行情实际抓取时间
  - `updated_at`: 本地入库更新时间
- 唯一键：
  - `UniqueConstraint("market", "code", name="table_serenity_aistocks_market_code_unique")`
- 新增 DB 方法：
  - `serenity_aistocks_latest_prices_replace(rows: List[dict]) -> bool`
    - 按 `market + code` 覆盖更新，不保留历史
  - `serenity_aistocks_latest_prices_query(items: List[dict]) -> List[...]`
    - 按页面传入的 `market + code` 批量查询
  - 可选补充：
    - `serenity_aistocks_latest_prices_query_all()`
    - 用于定时同步后或页面首屏整表 hydration

### 2. 在 Serenity 模块增加“规范化股票池 + 读库 hydration + 定时同步”能力

- 文件：`web/chanlun_chart/cl_app/serenity_aistocks.py`

#### 2.1 抽取统一股票键

- 新增辅助函数：
  - 从 workbook 行里提取统一的 `market/code/symbol`
  - A 股继续走 `normalize_a_share_code()`
  - 港股继续走 `normalize_hk_code()`
  - 美股使用大写 symbol
- 目标：
  - 页面、定时任务、数据库三者统一使用同一套 key

#### 2.2 增加数据库价格 hydration

- 新增辅助函数：
  - 例如 `_hydrate_sheet_rows_with_db_prices(rows)`
- 行为：
  - 读取 sheet 行数据后，提取所有可报价行的 `market + code`
  - 调用 `db.serenity_aistocks_latest_prices_query(...)`
  - 把查到的数据库价格回填到每一行：
    - `price_text`
    - `rate_text`
    - `price_status`
    - `updated_at`
  - 未查到数据时：
    - 保持 `pending`
    - 页面文案显示为“价格加载中”或“等待后台同步”

#### 2.3 页面首屏改为读库

- 修改：
  - `get_serenity_aistocks_sheet(sheet_slug)`
- 现状：
  - 只返回 Excel 行数据
- 改后：
  - 在返回 detail 前，先做数据库 hydration
- 结果：
  - Jinja 首屏渲染时直接带上数据库里的最新价，不需要等前端首次请求后才看到价格

#### 2.4 价格接口改为读库接口

- 路由仍保留：
  - `POST /serenity/aistocks/prices`
- 但语义改为：
  - 只从数据库读取最新价，不再临时直连行情源
- 结果：
  - 前端轮询只读取本地数据库，负载更稳定
  - 页面体验更一致，避免每个打开页面的用户都触发一次外部行情抓取

#### 2.5 新增后台同步函数

- 新增函数建议：
  - `collect_serenity_aistocks_quote_items()`
    - 遍历 workbook 所有 sheet，收集唯一的可报价标的
  - `sync_serenity_aistocks_latest_prices(db_instance=None) -> dict[str, Any]`
    - 按市场分组抓取 snapshot
    - 格式化为数据库记录
    - 调用 `db.serenity_aistocks_latest_prices_replace(...)`
    - 返回统计信息：
      - `total_candidates`
      - `success_count`
      - `unsupported_count`
      - `error_count`
      - `run_at`

### 3. 在应用启动时注册定时任务

- 文件：`web/chanlun_chart/cl_app/__init__.py`
- 参考现有 `jin10` 调度模式，新增：
  - `serenity_aistocks_price_sync_status` 状态字典
  - `_run_serenity_aistocks_price_sync_job()`
  - `_start_serenity_aistocks_price_sync(interval_seconds=60)`
- 调度配置建议：
  - `trigger="interval"`
  - `seconds=60`
  - `replace_existing=True`
  - `coalesce=True`
  - `max_instances=1`
  - `next_run_time=datetime.datetime.now()`
- 任务位置：
  - 在 app 初始化阶段完成注册，使服务启动后自动开始每分钟抓一次
- 错误策略：
  - 失败只记录日志和状态，不中断 Flask 启动

### 4. 调整前端文案，让页面表达“来自数据库”

- 文件：`web/chanlun_chart/cl_app/templates/serenity_aistocks_sheet.html`
- 页面行为调整：
  - 首屏直接显示数据库回填的最新价格
  - 若库里暂无记录：
    - 展示“等待后台同步”而不是让用户误解为页面故障
  - 轮询仍可保留，但轮询目标改成数据库读接口
- 展示增强：
  - 在价格列增加“更新时间”提示或 title
  - 明确说明当前价格来自本地缓存/数据库最新同步

### 5. 增加测试，覆盖新链路

- 文件：`test/test_serenity_aistocks.py`
- 需要补的测试：
  - `get_serenity_aistocks_sheet()` 会把数据库价格回填到 rows
  - `/serenity/aistocks/prices` 改为读库而不是直接抓 snapshot
  - 页面模板在有数据库价格时首屏就能渲染真实值
  - 页面模板在无数据库价格时显示“等待后台同步”

- 文件：`test/test_a_share_matches_quotes.py`
- 保持现有代码归一化测试不动，只在新测试里复用，不扩散改动范围

- 可选新增测试文件：
  - `test/test_serenity_aistocks_db_sync.py`
- 建议覆盖：
  - `sync_serenity_aistocks_latest_prices()` 对重复股票去重
  - 同一个 `market + code` 多 sheet 复用同一条数据库最新价
  - 入库采用覆盖更新，而不是累积插入

## Assumptions & Decisions

- 不引入新数据库服务，不使用 Supabase，不新建外部缓存层。
- 使用当前项目的 `sqlite` 主库作为价格最新值存储。
- 只保留“最新价”，不保留历史快照。
- 页面初始显示优先读数据库，不再把“是否能看到价格”依赖于页面打开后的实时抓价成功与否。
- 前端价格接口保留，是为了轮询数据库最新值，不再直接访问外部行情源。
- Excel 内容仍然是唯一股票列表来源，不单独维护一份数据库股票池表。
- 若某标的当前无法抓到 snapshot：
  - 数据库可写入 `status = unsupported` 或 `error`
  - 页面显示 `价格不可用` 或 `等待后台同步`
  - 不因单个标的失败影响整次同步

## Verification Steps

### 单元与集成验证

- 运行：
  - `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest test/test_serenity_aistocks.py -q`
- 若拆出独立同步测试，再运行：
  - `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest test/test_serenity_aistocks_db_sync.py -q`

### 行为验证

- 启动应用后，确认 scheduler 注册成功，日志中能看到 `Serenity AI Stocks` 定时抓价任务执行。
- 首次启动后的 1 分钟内，数据库中出现 `cl_serenity_aistocks_latest_price` 表记录。
- 打开 `/serenity/aistocks/<sheet_slug>`：
  - 首屏不再依赖即时行情抓取
  - 若数据库已有记录，直接展示真实价格
  - 若数据库尚未同步，显示“等待后台同步”
- 前端轮询触发后：
  - 只读取数据库接口
  - 不再直接触发外部行情抓取

### 回归检查

- 检查 `serenity_aistocks` 原有页面结构不变：
  - sheet 总览页仍正常
  - 明细页列顺序仍保持 Excel 原始列 + `价格`
- 检查价格方向色逻辑未回退：
  - 上涨红、下跌绿、加载中灰、不可用浅灰
