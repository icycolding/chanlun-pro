## Summary
- 目标：把 `a_share_matches` 中“主题指数 + 相关个股日线历史”的读取方式，从“每次直接向交易所全量拉取”改为“数据库持久化缓存 + 请求时增量补齐”。
- 用户已明确选择：
  - 范围：`主题指数 + 个股日线`
  - 落库方式：`只缓存成分股K线`
  - 刷新策略：`请求时增量补齐`
- 实现方向：优先复用现有 `db.klines_*` 能力，不新建主题指数专用表；数据库只存成分股日线，主题指数仍在请求时从库中快速合成。

## Current State Analysis
- 当前主题指数历史图入口位于：
  - `web/chanlun_chart/cl_app/__init__.py`
  - 路由：`POST /a_share_matches/theme_index_history`
  - 当前直接调用 `build_theme_index_history(...)`
- 当前主题指数历史数据读取位于：
  - `web/chanlun_chart/cl_app/a_share_matches_catalog.py`
  - `_load_theme_index_constituent_histories(...)`
  - 当前逻辑是对每个成分股直接执行：
    - `get_exchange(Market.A).klines(normalized_code, "d", args={"pages": pages})`
  - 这意味着每次打开主题指数历史图，都会重新从交易所拉各成分股日线
- 当前主题指数已经有固定基准日口径：
  - `build_theme_index_reference_closes(...)`
  - `build_theme_index_history_series(...)`
  - `build_theme_index_live_snapshot(...)`
  - 说明“指数计算逻辑”已经稳定，瓶颈主要在“成分股历史数据获取方式”
- 当前首页主题指数实时卡片位于：
  - `web/chanlun_chart/cl_app/templates/a_share_matches.html`
  - 前端通过 `/a_share_matches/theme_index_snapshots` 请求当前主题指数快照
  - 该快照最终也依赖后端成分股行情和参考状态
- 仓内已有可复用的数据库能力：
  - `src/chanlun/db.py`
  - `db.klines_query(...)`
  - `db.klines_last_datetime(...)`
  - `db.klines_insert(...)`
  - 这些接口已支持：
    - 按 `market + code + frequency`
    - 查询起止时间
    - 查询最后一条 K 线时间
    - 批量写入 K 线
- 仓内已有一套“先读库、必要时补交易所、然后回写”的模式可参考：
  - `web/chanlun_chart/cl_app/news_vector_api.py`
  - `_persist_exchange_price_bars(...)`
  - `_query_price_bars_from_db(...)`
  - `_query_price_bars_from_exchange(...)`
  - `_load_historical_price_bars(...)`
- 当前仍缺失：
  - 面向 `a_share_matches` 主题指数的“数据库优先 + 增量补齐”封装
  - 主题指数参考日缓存与历史日线缓存的一致性策略
  - 个股日线详情页对这套缓存的复用

## Proposed Changes
### 1. 抽出主题指数专用的日线缓存加载器
- 文件：`web/chanlun_chart/cl_app/a_share_matches_catalog.py`
- 修改内容：
  - 把当前 `_load_theme_index_constituent_histories(...)` 从“直接打交易所”改为“数据库优先加载器”
  - 新增一组 helper，职责建议如下：
    - `_normalize_theme_index_kline_rows(...)`
    - `_query_theme_index_klines_from_db(...)`
    - `_fetch_theme_index_klines_from_exchange(...)`
    - `_persist_theme_index_klines_to_db(...)`
    - `_load_theme_index_constituent_histories_from_db(...)`
  - 目标行为：
    - 先查 `db.klines_query(market="a", code=..., frequency="d")`
    - 如果数据库无数据或不足，再决定向交易所补历史
    - 补回来的数据用 `db.klines_insert(...)` 持久化
    - 最终返回统一的 `rows` 结构供 `build_theme_index_history_series(...)` 使用
- 原因：
  - 主题指数计算逻辑已经稳定，数据读取层独立改造风险最低

### 2. 实现“最后一次到现在”的增量补齐
- 文件：`web/chanlun_chart/cl_app/a_share_matches_catalog.py`
- 修改内容：
  - 对每个成分股日线读取加入增量判断：
    - 使用 `db.klines_last_datetime("a", code, "d")` 读取数据库最后日期
    - 若数据库为空：
      - 首次全量拉取足够长的历史
    - 若数据库已有数据：
      - 只补“最后日期之后到现在”的缺口
  - 增量补齐策略：
    - `lookback=max/all` 时：
      - 先从数据库取全量或大窗口
      - 仅当数据库最新日期落后时，再向交易所取增量并插入
    - `lookback=20/60/250` 时：
      - 仍以数据库为主，只取所需窗口
      - 若最近窗口不足，再增量补齐
- 关键设计：
  - 对于日线，增量判断以自然日或交易日最近条目为准
  - 不需要每次再按 `pages=60` 全量扫历史

### 3. 固定参考日状态也改为数据库驱动
- 文件：`web/chanlun_chart/cl_app/a_share_matches_catalog.py`
- 修改内容：
  - 当前 `_load_theme_index_reference_state(...)` 会调用 `_load_theme_index_constituent_histories(..., range_mode="max")`
  - 改造后应改为走数据库加载器，确保：
    - 参考日来自数据库中的共同最早可用日期
    - 只有当数据库缺历史时，才向交易所补齐
  - 保留已有的 `_THEME_INDEX_REFERENCE_STATE_CACHE`
  - 但增加失效/重算边界：
    - 进程内缓存仅作为短期加速
    - 真正数据源以数据库为准
- 原因：
  - 用户已经要求统一参考日口径，不能因为每次现拉历史不同而改变基准

### 4. 首页主题指数实时快照继续复用同一套参考状态
- 文件：`web/chanlun_chart/cl_app/a_share_matches_catalog.py`
- 关联文件：`web/chanlun_chart/cl_app/__init__.py`
- 修改内容：
  - `build_theme_index_live(...)` / `_load_theme_index_live_snapshot(...)`
  - 改为依赖数据库驱动的参考状态
  - 确保首页卡片与历史图弹窗：
    - 用的是同一个 `reference_date`
    - 不会出现历史图换了基准、实时卡片还在旧口径的问题
- 原因：
  - 这次需求本质是“性能优化”，但前提是不能破坏前面刚修好的“口径一致性”

### 5. 个股日线也纳入同一套数据库优先路径
- 文件：`web/chanlun_chart/cl_app/a_share_matches_catalog.py`
- 关联文件：`web/chanlun_chart/cl_app/__init__.py`
- 修改内容：
  - 这次范围用户要求是“主题指数 + 个股日线”
  - 计划将与 `a_share_matches` 主题相关的 A 股个股历史读取也统一到数据库优先
  - 具体执行上优先覆盖：
    - 主题指数成分股
    - 主题扩展详情页中用到的 A 股日线
  - 若当前个股图表直接走 TradingView 历史接口，不在本轮替换整站；仅确保 `a_share_matches` 相关日线入口复用数据库缓存
- 说明：
  - 这里的“个股日线”优先理解为该功能链路内的相关个股历史，不扩散到全站所有行情模块

### 6. 参考 `news_vector_api.py` 的价格缓存模式做最小复用
- 文件：`web/chanlun_chart/cl_app/a_share_matches_catalog.py`
- 参考文件：`web/chanlun_chart/cl_app/news_vector_api.py`
- 修改内容：
  - 借鉴其模式，不直接复制所有逻辑
  - 重点复用这些思想：
    - 规范化 dataframe 后落库
    - 数据库优先查询
    - 仅在缺失或过旧时打交易所
    - 失败时可回退为现有库内数据
- 原因：
  - 仓里已有成熟样板，能减少重新设计缓存策略的风险

### 7. 前端无需改交互，但要兼容更快的响应路径
- 文件：`web/chanlun_chart/cl_app/templates/a_share_matches.html`
- 修改内容：
  - 原则上不改已有交互结构：
    - 顶部主题指数卡
    - 历史图弹窗
    - K线/趋势切换
  - 仅在必要时补充更准确的状态文案，例如：
    - “历史数据加载中”
    - “正在增量更新到最新交易日”
  - 如果不需要新的状态提示，可不改模板逻辑
- 结论：
  - 本次主要是后端数据层优化，前端改动应最小化

### 8. 测试更新
- 文件：`test/test_a_share_matches_theme_index.py`
- 新增/修改测试：
  - 验证参考日不因窗口切换而改变
  - 验证实时指数继续使用固定参考日
  - 新增数据库优先/增量补齐行为测试，推荐 monkeypatch：
    - `db.klines_query`
    - `db.klines_last_datetime`
    - `db.klines_insert`
    - `get_exchange(...).klines`
  - 关键场景：
    - 库里已有全量历史，不触发交易所请求
    - 库里已有旧历史，只补最后日期之后的数据
    - 库里为空时，首次拉取并回写
    - 交易所补齐失败时，优先回退库内已有数据
- 文件：`test/test_a_share_matches_catalog.py`
- 新增/修改测试：
  - 模板结构一般无需大改
  - 如果增加了新的状态文案或接口名，需要同步断言
- 如需补接口级测试，可加：
  - `POST /a_share_matches/theme_index_history`
  - `POST /a_share_matches/theme_index_snapshots`
  - 验证其在缓存命中时不依赖全量现拉历史

## Assumptions & Decisions
- 已确认决策：
  - 优化范围：`主题指数 + 个股日线`
  - 持久化内容：`只缓存成分股K线`
  - 默认刷新方式：`请求时增量补齐`
- 本次明确不做：
  - 不新建主题指数专用历史表
  - 不做后台定时任务预热
  - 不把全站所有行情历史都一起改掉
- 实现决策：
  - 优先复用 `src/chanlun/db.py` 的 `db.klines_*`
  - 主题指数仍为“请求时现场合成”
  - 数据库存的是 A 股成分股日线，不直接存主题指数结果
- 风险与边界：
  - 参考日依赖所有成分股共同最早可用日期；若某些成分股历史过短，参考日可能后移
  - SQLite 下 `db.klines_insert(...)` 是逐条 upsert，首次全量写入会比纯内存方案慢，但后续增量收益明显
  - 若交易所接口无法精确按起止日期增量拉取，计划采用“按较小 pages 拉最近窗口 + 去重入库”的实用策略

## Verification Steps
1. 单元测试：
   - `python -m pytest test/test_a_share_matches_theme_index.py -q`
   - 重点验证：
     - 固定参考日
     - 库优先
     - 增量补齐
     - 回写数据库
2. 页面结构回归：
   - `python -m pytest test/test_a_share_matches_catalog.py -q`
3. 详情链路回归：
   - `python -m pytest test/test_a_share_stock_analysis.py -q`
4. 手工验证：
   - 首次打开主题指数历史图：
     - 会较慢但能回写数据库
   - 第二次打开同主题历史图：
     - 明显变快
   - 隔一段时间再次打开：
     - 只补最后一次到现在的数据
   - 切换 `20日 / 60日 / 250日 / 最长`：
     - 参考日不变
     - 相同日期指数值不变
5. 诊断检查：
   - `a_share_matches_catalog.py`
   - 如有必要再检查 `__init__.py`
