# aistocks_research.json — 研究数据 Schema

**当前版本**: `schema_version: 2`
**键**: 股票中文名（如 `"国瓷材料"`），`_` 开头的键为元数据。
**读取层**: `serenity_aistocks_serenity_fit._resolve_profile` 按名优先读取；详情页 `a_share_stock_analysis.py` 消费结构化视图组。
**生成**: 点击分析三轮流水线（gather→analyze→critique），产出后过 `scripts/validate_serenity_research.py` 质量闸门。

## 铁律
1. **联网实证**：禁用模型记忆，所有数字/结论须来自近 12 个月公开信息。
2. **名称↔代码核验**：`code_verified` 必须核对无误（历史 bug：sh603062 实为麦加芯彩非江南新材）。
3. **不编造精确数字**：无法核实的市值/份额/估值倍数留定性描述，并置 `live_number_source_required:true`。
4. **事实/假设分离**、**逐维置信**、**证据分层 tier**。

## 字段全集（v2）

### 顶层标识
| 字段 | 说明 |
|---|---|
| `code_in_xlsx` | xlsx 原始代码 |
| `code_verified` | 核验后代码 `^(sh\|sz\|bj\|hk)?\d{5,6}$` |
| `code_fix_note` | 若代码有误的修正说明 |
| `verified_at` | `YYYY-MM-DD` |
| `fit_status` | `fit`/`partial_fit`/`not_fit`/`watch`（扁平兜底保留） |
| `fit_reason_short` / `fit_reason_detail` / `fit_basis` | 扁平兜底保留 |

### 详情页结构化视图组（9 组，须全部产出）
| 组 | 字段 | 语义 |
|---|---|---|
| `selection_reason` | `summary`, `fit_basis` | 投资论点摘要 |
| `scarcity_view` | `label`, `detail` | 稀缺性（Serenity 卡点一维）；label 如 强/中/弱 |
| `capacity_view` | `label`, `detail` | 产能/进入壁垒 |
| `pricing_view` | `label`, `detail` | 定价权 |
| `segment_market_view` | `market_size_text`, `company_share_text`, `share_level` | 细分市场空间 |
| `sector_context_view` | `sector_name`,`sector_role`,`market_size_text`,`growth_outlook`,`company_position_text`,`company_share_text`,`share_level`,`evidence_note` | 板块背景 |
| `industry_chain_view` | `upstream`,`midstream`,`downstream`,`company_link_position`,`choke_point_note` | 产业链定位 |
| `market_cap_research` | `current_text`,`upside_text`,`downside_text`,`rationale`,`live_number_source_required` | 市值研究 |
| `evidence_sources` | `[{title,summary,url,source_type,tier}]` | 证据；`tier`=1 一手披露/交易所 · 2 权威财媒 · 3 其他 |

### 新增 8 维（v2）
| 组 | 字段 | 语义 |
|---|---|---|
| `financials_view` | `revenue_segments:[{name,pct,trend}]`,`revenue_trend_3y`,`margin_text`,`operating_leverage_text` | 财务：营收分部占比/3Y 趋势/毛利/经营杠杆 |
| `moat_view` | `moat_types:[..]`,`durability`(强/中/弱),`detail` | 护城河：品牌/成本/网络/转换成本/规模/IP |
| `valuation_view` | `pe_text`,`pb_text`,`peg_text`,`vs_history_text`,`vs_peers_text`,`verdict`(低估/合理/高估) | 估值 |
| `catalysts_view` | `[{window,event,impact}]` | 12 月催化日历 |
| `risks_view` | `[{risk,impact,monitor}]` | Top5 风险 + 监控指标 |
| `thesis_view` | `variant_perception`,`bull_points:[..]`,`bear_points:[..]` | 变量感知（市场忽视了什么） |
| `scenario_view` | `bull:{prob,target,drivers}`,`base:{..}`,`bear:{..}` | 牛/基准/熊三情景 |
| `confidence` | `overall`(高/中/低),`by_dimension:{dim:level}`,`evidence_tier_summary` | 置信度 |

### Serenity 方法论认证（v3 起必填）
`serenity_certification`：用 Serenity 原生 14 点清单（methodology.md §15）对个股做正式认证。
| 字段 | 语义 |
|---|---|
| `verdict` | fit/partial_fit/not_fit/watch（`fit_status` 派生自此） |
| `score` | 已通过(yes)条数/14 |
| `checklist` | 14×`{id,name,result(yes/partial/no/na),evidence,source_url}` |
| `bottleneck_map` | 多跳 BOM 链路（原料→…→模组）+ 每层卡点方 |
| `disqualifiers` | 命中的否决项（大额定增/减持/高质押/高息债等） |
| `anti_patterns_checked` | 已排查的反模式（纯 TA/内部人卖出/混淆链路层/情绪） |
| `summary` | 是否符合的一句话结论 |
认证从严如实：多数 A 股非 US 式独家卡点，应给 partial/not_fit；`na` 仅用于真不适用（如 #13 披露权重），闸门限制 na>6 判不合格。

## 向后兼容
- v1 条目（无新组）由详情页 `_merge_selection_metrics` 与默认值合并，仍可渲染；闸门宽松。
- v2 条目（有视图组、无认证）强校验视图组，不要求认证。
- **v3 起**强制 `serenity_certification`。runner 新产出打 `schema_version:3`。
