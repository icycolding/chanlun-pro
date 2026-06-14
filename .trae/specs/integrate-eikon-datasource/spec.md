# Eikon（EKION）数据源首用接入 Spec

## Why
当前项目的 A 股与外汇价格数据主要依赖 Tushare/AKShare/yfinance 等来源，缺少对 Refinitiv Workspace/Eikon（Eikon Data API）数据的统一接入能力。接入 Eikon SDK 可提升数据覆盖与一致性，并为后续新闻/字段查询扩展打基础。

## What Changes
- 新增 Eikon 历史行情数据源（优先）以支持 A 股与外汇的日线历史数据获取
- 新增“自然语言/别名 -> 项目标准 symbol”的解析层（首期覆盖少量 A 股常用别名，如“茅台”）
- 新增“项目标准 symbol -> RIC”的 symbology 映射与本地缓存（优先缓存，缺失时调用 `ek.get_symbology`）
- 将 Eikon 数据源加入现有数据源回退链（Eikon 不可用时自动回退到现有来源）
- 新增启动前检查（SDK 可导入、App Key 配置等）与 `.env.example` 配置项
- 明确首期范围：仅日线（1D），仅 A 股与外汇；新闻与快照字段能力不纳入首期

## Impact
- Affected specs: 历史行情获取、数据源路由/回退、symbol 解析、运行前检查
- Affected code: 后端数据加载与回测数据路由（loader/registry/runner/preflight）、环境变量配置、单元测试

## ADDED Requirements

### Requirement: Eikon 历史行情数据源
系统 SHALL 提供一个新的数据源实现，使用 `refinitiv.data.eikon` SDK 通过 `ek.get_timeseries` 拉取历史行情，并输出为项目统一 OHLCV schema。

#### Scenario: 成功获取 A 股日线
- **WHEN** 用户请求标的 `600519.SH` 的 `1D` 历史行情（指定 start/end）
- **THEN** 系统优先使用 Eikon 数据源拉取数据（若可用）
- **AND** 返回数据包含 `trade_date/open/high/low/close/volume`（volume 缺失时补 0）
- **AND** 数据按时间升序且 `trade_date` 可解析为时间索引

#### Scenario: 成功获取外汇日线
- **WHEN** 用户请求标的 `EUR/USD` 的 `1D` 历史行情（指定 start/end）
- **THEN** 系统优先使用 Eikon 数据源拉取数据（若可用）
- **AND** 返回数据为项目统一 OHLCV schema（volume 缺失时补 0）

#### Scenario: Eikon 不可用自动回退
- **WHEN** 未配置 `EIKON_APP_KEY` 或 SDK 不可用/请求失败
- **THEN** 系统 SHALL 自动回退到既有数据源链路（A 股：tushare/akshare；外汇：akshare/yfinance）
- **AND** 不应导致上层请求失败（除非所有回退均失败）

### Requirement: 自然语言/别名 Symbol 解析
系统 SHALL 支持将用户输入的自然语言别名解析为项目标准 symbol，以用于数据源路由与回测。

#### Scenario: 别名解析成功
- **WHEN** 用户输入 “茅台”
- **THEN** 系统返回候选解析结果，首选为 `600519.SH`

#### Scenario: 歧义返回候选
- **WHEN** 用户输入存在歧义的名称（例如多个证券同名/简称）
- **THEN** 系统 SHALL 返回多个候选并标记为 `ambiguous`
- **AND** 系统不应默认选取其中一个候选

### Requirement: 项目标准 Symbol 到 RIC 的映射与缓存
系统 SHALL 提供将项目标准 symbol 映射到 Eikon RIC 的能力，并对映射结果进行本地缓存，以减少重复 symbology 查询。

#### Scenario: 缓存命中
- **WHEN** 请求 `600519.SH` 的 RIC 映射且缓存已存在
- **THEN** 系统直接返回缓存的 RIC，不调用 `ek.get_symbology`

#### Scenario: 缓存缺失时通过 symbology 查询
- **WHEN** 请求 `600519.SH` 的 RIC 映射且缓存缺失
- **THEN** 系统调用 `ek.get_symbology`（或等价 symbology 能力）获取 RIC
- **AND** 将结果写入缓存后返回

## MODIFIED Requirements

### Requirement: 既有数据源路由/回退链
系统 SHALL 在不破坏现有功能的前提下，将 Eikon 数据源加入回退链，并确保在 Eikon 不可用时行为与现有版本一致。

## REMOVED Requirements
无

