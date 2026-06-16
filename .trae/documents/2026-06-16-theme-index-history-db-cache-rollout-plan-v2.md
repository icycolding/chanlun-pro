## Summary
- 目标：把 `a_share_matches` 主题指数历史数据的获取稳定为“数据库持久化 + 请求时增量补齐”，避免每次都全量向交易所拉历史日线。
- 成功标准：
  - 历史图和顶部实时指数卡继续共用同一个固定 `reference_date`
  - 已缓存成分股日线时，不再触发不必要的交易所历史拉取
  - 数据落后时，只补“数据库最后一日之后到当前”的增量区间
  - `20/60/250/max` 切换时，同一日期的指数值不因窗口变化而漂移
- 范围：本轮以 `a_share_matches` 主题指数成分股日线为核心，不新建主题指数表；主题指数仍在请求时由成分股 K 线现场合成。

## Current State Analysis
- 主题指数历史接口已存在于 `web/chanlun_chart/cl_app/__init__.py`
  - `POST /a_share_matches/theme_index_history`
  - `POST /a_share_matches/theme_index_snapshots`
  - 两者分别调用 `build_theme_index_history(...)` 与 `build_theme_index_live(...)`
- 主题指数历史数据加载逻辑位于 `web/chanlun_chart/cl_app/a_share_matches_catalog.py`
  - 已存在 `_load_theme_index_constituent_history(...)`
  - 已存在 `_query_theme_index_klines_from_db(...)`
  - 已存在 `_persist_theme_index_klines_to_db(...)`
  - 已存在 `_fetch_theme_index_klines_from_exchange(...)`
  - 已存在 `_theme_index_full_history_cache_key(...)`
- 当前仓库中的实现已经体现出本轮方案的核心形态：
  - 先用 `db.klines_query(...)` 读取成分股日线
  - 用 `db.klines_last_datetime(...)` 判断最后缓存日期
  - 必要时向交易所拉取最近区间或全量区间
  - 用 `db.klines_insert(...)` 将新增日线持久化
  - 用 `db.cache_get/cache_set(...)` 持久化“该股票是否已完成 full history 装载”的标记
- 固定基准日的指数口径也已经在同一文件中存在：
  - `build_theme_index_reference_closes(...)`
  - `build_theme_index_history_series(...)`
  - `build_theme_index_live_snapshot(...)`
  - `merge_theme_index_live_snapshot(...)`
- 测试文件 `test/test_a_share_matches_theme_index.py` 已有两类关键回归用例：
  - 数据库命中时不得再打交易所
  - 数据库落后时只补增量并回写
- 通过本次环境探索，没有发现 `a_share_matches` 下另一个独立的“个股历史图接口”直接复用或绕开这套主题指数缓存；因此本轮计划以主题指数成分股 K 线链路为交付主线，不扩散到全站所有个股图表入口。

## Proposed Changes
### 1. 固化数据库优先加载器为唯一历史入口
- 文件：`web/chanlun_chart/cl_app/a_share_matches_catalog.py`
- 做法：
  - 继续以 `_load_theme_index_constituent_history(...)` 作为单只成分股历史加载的唯一入口
  - 保持其职责边界清晰：
    - `_query_theme_index_klines_from_db(...)` 只负责取库内日线
    - `_fetch_theme_index_klines_from_exchange(...)` 只负责向交易所请求规范化后的日线
    - `_persist_theme_index_klines_to_db(...)` 只负责将新增记录落库
    - `_merge_theme_index_history_rows(...)` 只负责按交易日去重合并
- 原因：
  - 当前核心逻辑已经落在该路径上，继续收敛到单入口最利于后续维护和问题定位。

### 2. 明确增量补齐判定规则
- 文件：`web/chanlun_chart/cl_app/a_share_matches_catalog.py`
- 做法：
  - 非 `max/all` 模式：
    - 先读库内全部或足够窗口的日线
    - 若库内最后日期落后于今天，触发最近窗口增量补齐
    - 若库内条数不足当前窗口，再补最近窗口并按日期去重
  - `max/all` 模式：
    - 若库内为空或尚未标记 `full_history`，执行一次全量历史装载
    - 装载成功后写入 `a_share_matches:theme_index:full_history:{code}:d`
    - 后续再请求 `max/all` 时只按最后缓存日期补最近尾部
  - 交易所返回的是包含重叠区间的最近若干页时，始终以日期去重后再回写数据库
- 原因：
  - 这正是“首次可能慢、后续只补尾部”的目标行为，也是和当前代码最一致的执行方式。

### 3. 保持固定参考日口径不被缓存策略破坏
- 文件：`web/chanlun_chart/cl_app/a_share_matches_catalog.py`
- 做法：
  - `build_theme_index_live(...)` 与 `build_theme_index_history(...)` 都必须继续依赖同一份参考状态
  - 参考状态加载时统一走 `_load_theme_index_constituent_histories(..., range_mode="max")`
  - 只有在库中没有 full history 或历史明显缺失时，才允许触发全量补齐
  - 禁止因用户切换 `20/60/250/max` 窗口而重置 `reference_date`
- 原因：
  - 用户此前已明确要求“以某一日为基准，当前指数与历史图保持一致”，性能优化不能破坏这一口径。

### 4. 前端维持现有接口和展示结构
- 文件：`web/chanlun_chart/cl_app/templates/a_share_matches.html`
- 做法：
  - 保持现有历史图弹窗、顶部主题指数卡、K 线/趋势切换与 `reference_date / base 1000` 展示不变
  - 除非后端返回结构发生变化，否则本轮不主动调整前端 JS 或模板
  - 只有在人工验证发现用户感知问题时，才补充轻量状态文案，例如“正在增量更新到最新交易日”
- 原因：
  - 本次是数据层性能优化，不应引入额外交互回归风险。

### 5. 将“个股日线”范围限定为主题指数成分股底层缓存，而非全站个股图表改造
- 文件：`web/chanlun_chart/cl_app/a_share_matches_catalog.py`
- 说明：
  - 结合当前仓库入口，用户提到的“历史数据保存在数据库”与“只拉最后一次到现在”直接对应的是主题指数历史图所依赖的成分股 K 线
  - 本轮不新增全站统一个股历史缓存框架，不改 TradingView 或其他独立行情模块
  - 主题指数成分股的 K 线一旦落库，相关 `a_share_matches` 计算链路即可直接复用
- 原因：
  - 这样能保持范围收敛，并且完全贴合当前已存在的后端实现形态。

### 6. 补齐和锁定测试覆盖
- 文件：`test/test_a_share_matches_theme_index.py`
- 做法：
  - 保留并通过以下关键测试：
    - 数据库命中时不打交易所
    - 数据库落后时只补增量并回写
    - 固定参考日不因窗口切换改变
  - 若执行时发现空白，再补两类测试：
    - 首次空库请求 `max` 时会执行 full history 装载并写入 full-history marker
    - 交易所补齐失败时，若库中已有旧数据，历史接口仍返回库内可用结果而不是整页失败
- 文件：`test/test_a_share_matches_catalog.py`
- 做法：
  - 继续验证页面包含主题指数历史与快照接口钩子
  - 仅当响应结构或文案变更时再补模板断言
- 原因：
  - 此次需求本质是“行为优化”，单元测试是防止后续再次退回全量现拉的关键护栏。

## Assumptions & Decisions
- 已锁定决策：
  - 持久化对象：只存 A 股成分股日线，不存主题指数结果行
  - 刷新方式：请求时增量补齐，不引入定时预热任务
  - 指数计算：继续现场合成，固定 `reference_date`，基点 `1000`
- 范围边界：
  - 本轮仅处理 `a_share_matches` 主题指数历史链路
  - 不顺带重构全站其他行情或图表模块
  - 不新建主题指数专用数据库表
- 技术假设：
  - `db.klines_insert(...)` 的 upsert 语义可接受重叠窗口写入
  - 交易所最近若干页返回中即便包含重叠日期，也能通过 `_merge_theme_index_history_rows(...)` 去重
  - `db.cache_set(..., expire=0)` 可作为长期 full-history 标记
- 风险与处理：
  - 若某成分股上市较晚，参考日仍以所有可用成分股的共同最早日期为准
  - SQLite 首次 full-history 写入可能偏慢，但只发生在冷启动或首次全量装载
  - 若交易所接口临时失败，应优先回退到数据库中已有的可用历史数据

## Verification Steps
1. 单测回归
   - `python -m pytest test/test_a_share_matches_theme_index.py -q`
   - 关注：
     - fixed reference date
     - db cache hit
     - incremental backfill
     - db persistence
2. 主题页结构回归
   - `python -m pytest test/test_a_share_matches_catalog.py -q`
3. 详情链路回归
   - `python -m pytest test/test_a_share_stock_analysis.py -q`
4. 诊断检查
   - 优先检查 `web/chanlun_chart/cl_app/a_share_matches_catalog.py`
   - 如有模板微调，再检查 `web/chanlun_chart/cl_app/templates/a_share_matches.html`
5. 手工验收
   - 首次打开某主题“最长历史”时允许较慢，但应完成落库
   - 第二次打开同主题历史图应明显更快
   - 库里已有最近历史时，不应再次全量请求
   - 隔天或历史落后后再次打开，只补最后一次到现在的缺口
   - 顶部实时指数卡与历史图的最新点位继续共享同一 `reference_date`
