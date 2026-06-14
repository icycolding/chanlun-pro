# Tasks
- [x] Task 1: 建立 Eikon 接入的配置与预检
  - [x] 添加环境变量约定与 `.env.example`（EIKON_APP_KEY，可选 EIKON_ENABLED）
  - [x] 在启动预检中加入 SDK 可导入与 App Key 检查，并提供清晰提示

- [x] Task 2: 实现 symbol_resolver（自然语言/别名 -> 项目标准 symbol）
  - [x] 定义解析结果数据结构（resolved/ambiguous/not_found + candidates）
  - [x] 新增最小证券主数据（首期仅少量 A 股：至少包含“茅台”-> 600519.SH）
  - [x] 覆盖标准输入：`NNNNNN.SZ/SH/BJ`、裸 6 位代码、`XXX/YYY` 外汇对
  - [x] 添加单元测试：别名命中、裸代码命中、歧义返回候选、未命中

- [x] Task 3: 实现 eikon_symbology（项目标准 symbol -> RIC）与缓存
  - [x] 实现缓存读取/写入（文件缓存即可）
  - [x] 缓存缺失时调用 `ek.get_symbology` 获取 RIC 并回写缓存
  - [x] 添加单元测试：缓存命中不触发外部调用、缓存缺失触发查询并写入

- [x] Task 4: 实现 eikon_loader（get_timeseries 历史行情）并接入 registry 回退链
  - [x] 初始化 Eikon SDK（set_app_key）并保证线程/重复初始化安全
  - [x] 拉取日线时间序列并标准化为统一 OHLCV
  - [x] A 股回退链：eikon -> tushare -> akshare
  - [x] 外汇回退链：eikon -> akshare -> yfinance
  - [x] 添加单元测试：标准化输出、Eikon 不可用触发回退链

- [x] Task 5: 端到端冒烟验证与文档核对
  - [x] 本地启动后端与前端，验证 `/health` 与 `/sessions` 等代理路径不报错
  - [x] 使用 2 个标的做冒烟：`600519.SH`、`EUR/USD`（1D）
  - [x] 确认在未配置 EIKON_APP_KEY 时行为与现有版本一致

# Task Dependencies
- Task 4 depends on Task 1, Task 2, Task 3
- Task 5 depends on Task 4
