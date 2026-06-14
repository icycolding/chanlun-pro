# IBKR 外汇/黄金自动投研（每日报告）

这个项目用于在 **IBKR（TWS / IB Gateway）** 可用的情况下，每日自动拉取历史行情，计算指标与情景结论，做一个轻量级策略回测摘要，并生成 **Markdown 报告**（可选转 PDF）。

默认覆盖：
- EURUSD、USDJPY、GBPUSD（IDEALPRO 外汇）
- XAUUSD（若你的 IBKR 账户/路由支持现货黄金）
- USDCNH（作为 USDCNY 的可用替代，IBKR 更常见的是 CNH）

并支持 **新闻分析**（按品种拉取最近 N 小时新闻标题、生成风险评分、分组展示）。新闻功能通常需要你在 IBKR 账户中订阅相应新闻提供商。

此外支持从网页“抓取金十快讯”的简易方案（不需要 secret-key，但页面结构可能变动，稳定性不如官方开放平台 API）。

## 1. 环境要求

- Python 3.10+
- 运行中的 TWS 或 IB Gateway（建议 Paper 账户先跑通）
- 已启用 API：`Enable ActiveX and Socket Clients`

安装依赖：
```bash
pip install -r requirements.txt --break-system-packages
```

> 可选：如果你希望输出 PDF，请确保系统里有 `pandoc`（或自行改成你偏好的 PDF 渲染方案）。

## 2. IBKR 端设置（必做）

以 IB Gateway 为例（TWS 类似）：
1) 端口：
   - Paper 常见：`7497`
   - Live 常见：`7496`
2) API → Settings：
   - ✅ Enable ActiveX and Socket Clients
   - （可选）✅ Read-Only API（如果你只做投研不交易）
   - 允许来自 `127.0.0.1` 的连接

## 3. 配置

复制一份配置：
```bash
cp config.example.yml config.yml
```

按需修改 `host/port/client_id`、品种列表、回测窗口等。

### 3.1 新闻配置（IBKR）

在 `config.yml` 中：
- `news.enabled: true`
- `news.source: ibkr`
- `news.lookback_hours`: 拉取最近多少小时新闻
- `news.providers`: 留空会自动探测你账户可用 providers；你也可以填 provider code 列表以减少请求量

如果报告里显示“未拉取到新闻”，常见原因：
- 你未订阅新闻源（TWS 里能看新闻不等于 API 可取，取决于订阅）
- provider 探测为空（账户权限/地区/时间段）
- 某些外汇/黄金合约 conId 没有对应新闻（可在 TWS 中换合约验证）

### 3.2 新闻配置（金十网页抓取）

在 `config.yml` 中设置：
- `news.enabled: true`
- `news.source: jin10_web`
- `jin10_web.url: https://www.jin10.com/`

限制与建议：
- 这是网页解析方案，**页面结构变化会导致解析失败**（我已做基础容错）
- 请控制抓取频率（盘中轮询建议 ≥ 30 秒）
- 若你能开通金十开放平台，建议改为官方 `open-data-api`（需要 `secret-key`，更稳定）

## 4. 生成报告

生成当日报告（默认输出到 `./reports/YYYY-MM-DD/`）：
```bash
python run_daily.py --config config.yml
```

指定日期（用于重跑某天的报告目录命名；数据仍是从 IB 拉取的历史序列）：
```bash
python run_daily.py --config config.yml --as-of 2026-04-03
```

可选输出 PDF（若本机有 pandoc）：
```bash
python run_daily.py --config config.yml --pdf
```

## 4.1 盘中实时抓取（控制台输出）

启动一个轮询进程，发现新快讯就打印：
```bash
python watch_jin10.py --interval 30
```

## 5. 定时运行（示例）

Linux cron（每天 17:00 生成）：
```cron
0 17 * * * /usr/bin/python3 /path/to/ibkr_fx_research/run_daily.py --config /path/to/ibkr_fx_research/config.yml >> /path/to/ibkr_fx_research/cron.log 2>&1
```

## 6. 常见问题

### Q1：连不上 127.0.0.1:7497？
- 确认 IB Gateway/TWS 已启动且端口一致
- 确认开启了 API Socket
- clientId 换一个数字（同一个 clientId 同时只能有一个连接）

### Q2：XAUUSD / USDCNH 拉不到数据？
IBKR 对不同账户、路由、权限会有差异。你可以在 TWS 里先搜索/加到 Watchlist，确认合约是否存在、是否有行情权限，然后在 `config.yml` 里替换为你账户可用的合约标识（后续我也可以按你 TWS 中的合约信息帮你改代码）。
