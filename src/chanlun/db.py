import datetime
import hashlib
import json
import re
import time
import warnings
from typing import Any, Dict, List, Optional, Union

import numpy as np
import pandas as pd
from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    func,
    inspect,
    or_,
    tuple_,
)
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import QueuePool

from chanlun import config, fun
from chanlun.base import Market
from chanlun.config import get_data_path

warnings.filterwarnings("ignore")

# https://docs.sqlalchemy.org/en/20/core/types.html

Base = declarative_base()


def _normalize_serenity_aistocks_market_code(market: str, code: str) -> tuple[str, str]:
    normalized_market = str(market or "").strip().lower()
    normalized_code = str(code or "").strip().upper()
    if not normalized_market or not normalized_code:
        return normalized_market, normalized_code
    if normalized_market == "a":
        if "." in normalized_code:
            return normalized_market, normalized_code
        if re.fullmatch(r"(SH|SZ|BJ)\d{6}", normalized_code):
            return normalized_market, f"{normalized_code[:2]}.{normalized_code[2:]}"
    elif normalized_market == "hk":
        digits = re.sub(r"\D", "", normalized_code)
        if digits:
            return normalized_market, f"KH.{digits.zfill(5)[-5:]}"
    elif normalized_market == "us":
        return normalized_market, normalized_code
    return normalized_market, normalized_code


class TableByCompanyFinancials(Base):
    """
    公司财务数据
    """
    __tablename__ = 'company_financials'
    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(10), nullable=False, comment='公司代码')
    name = Column(String(100), nullable=False, comment='公司名称')
    report_date = Column(Date, nullable=False, comment='报告期')
    statement_type = Column(String(50), nullable=False, comment='报表类型')
    item_name = Column(String(255), nullable=False, comment='项目名称')
    item_value = Column(Float, nullable=True, comment='项目值')

    __table_args__ = (
        UniqueConstraint('code', 'report_date', 'statement_type', 'item_name', name='_code_report_date_statement_item_uc'),
        Index('ix_code_report_date', 'code', 'report_date'),
    )

    def __repr__(self):
        return f'<TableByCompanyFinancials(code={self.code}, report_date={self.report_date}, statement_type={self.statement_type}, item_name={self.item_name})>'



class TableByCache(Base):
    # 各种乱七八杂的信息
    __tablename__ = "cl_cache"
    k = Column(String(100), unique=True, primary_key=True)  # 唯一值
    v = Column(Text, comment="存储内容")  # 存储内容
    expire = Column(
        Integer, default=0, comment="过期时间戳，0为永不过期"
    )  # 过期时间戳，0为永不过期
    # 添加配置设置编码
    __table_args__ = {"mysql_collate": "utf8mb4_general_ci"}


class TableByZxGroup(Base):
    # 自选组列表
    __tablename__ = "cl_zixuan_groups"
    __table_args__ = (
        UniqueConstraint("market", "zx_group", name="table_market_group_unique"),
    )
    market = Column(String(20), primary_key=True, comment="市场")
    zx_group = Column(String(20), primary_key=True, comment="自选组名称")
    add_dt = Column(DateTime, comment="添加时间")
    # 添加配置设置编码
    __table_args__ = {"mysql_collate": "utf8mb4_general_ci"}


class TableByZixuan(Base):
    # 自选表
    __tablename__ = "cl_zixuan_watchlist"
    id = Column(Integer, primary_key=True, autoincrement=True)
    market = Column(String(20), comment="市场")  # 市场
    zx_group = Column(String(20), comment="自选组")  # 自选组
    stock_code = Column(String(20), comment="标的代码")  # 标的代码
    stock_name = Column(String(100), comment="标的名称")  # 标的名称
    position = Column(Integer, comment="位置")  # 位置
    add_datetime = Column(DateTime, comment="添加时间")  # 添加时间
    stock_color = Column(String(20), comment="自选颜色")  # 自选颜色
    stock_memo = Column(String(100), comment="附加信息")  # 附加信息
    # 添加配置设置编码
    __table_args__ = {"mysql_collate": "utf8mb4_general_ci"}


class TableByAlertTask(Base):
    # 提醒任务
    __tablename__ = "cl_alert_task"
    __table_args__ = (
        UniqueConstraint("market", "task_name", name="table_market_task_name_unique"),
    )
    id = Column(Integer, primary_key=True, autoincrement=True)
    market = Column(String(20), comment="市场")  # 市场
    task_name = Column(String(100), comment="任务名称")  # 任务名称
    zx_group = Column(String(20), comment="自选组")  # 自选组
    frequency = Column(String(20), comment="检查周期")  # 检查周期
    interval_minutes = Column(Integer, comment="检查间隔分钟")  # 检查间隔分钟
    check_bi_type = Column(String(20), comment="检查笔的类型")  # 检查笔的类型
    check_bi_beichi = Column(String(200), comment="检查笔的背驰")  # 检查笔的背驰
    check_bi_mmd = Column(String(200), comment="检查笔的买卖点")  # 检查笔的买卖点
    check_xd_type = Column(String(20), comment="检查线段的类型")  # 检查线段的类型
    check_xd_beichi = Column(String(200), comment="检查线段的背驰")  # 检查线段的背驰
    check_xd_mmd = Column(String(200), comment="检查线段的买卖点")  # 检查线段的买卖点
    check_idx_ma_info = Column(String(200), comment="检查指数的均线")
    check_idx_macd_info = Column(String(200), comment="检查指数的MACD")
    is_run = Column(Integer, comment="是否运行")  # 是否运行
    is_send_msg = Column(Integer, comment="是否发送消息")  # 是否发送消息
    dt = Column(DateTime, comment="任务添加、修改时间")  # 任务添加、修改时间
    # 添加配置设置编码
    __table_args__ = {"mysql_collate": "utf8mb4_general_ci"}


class TableByAlertRecord(Base):
    # 提醒记录
    __tablename__ = "cl_alert_record"
    id = Column(Integer, primary_key=True, autoincrement=True)
    market = Column(String(20), comment="市场")  # 市场
    task_name = Column(String(100), comment="任务名称")  # 任务名称
    stock_code = Column(String(20), comment="标的")  # 标的
    stock_name = Column(String(100), comment="标的名称")  # 标的名称
    frequency = Column(String(10), comment="提醒周期")  # 提醒周期
    line_type = Column(String(5), comment="提醒线段的类型")  # 提醒线段的类型
    alert_msg = Column(Text, comment="提醒消息")  # 提醒消息
    bi_is_done = Column(
        String(10), comment="笔是否完成,如果是指标，则记录上穿或下穿"
    )  # 笔是否完成
    bi_is_td = Column(String(10), comment="笔是否停顿")  # 笔是否停顿
    line_dt = Column(DateTime, comment="提醒线段的开始时间")  # 提醒线段的开始时间
    alert_dt = Column(DateTime, comment="提醒时间")  # 提醒时间
    # 添加配置设置编码
    __table_args__ = {"mysql_collate": "utf8mb4_general_ci"}


class TableByTVMarks(Base):
    # TV 图表的 mark 标记 (在时间轴上的标记)
    __tablename__ = "cl_tv_marks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    market = Column(String(20), comment="市场")  # 市场
    stock_code = Column(String(20), comment="标的代码")  # 标的代码
    stock_name = Column(String(100), comment="标的名称")  # 标的名称
    frequency = Column(String(10), default="", comment="展示周期")  # 展示周期
    mark_time = Column(Integer, comment="标签时间戳")  # 标签时间戳
    mark_label = Column(String(2), comment="标签")  # 标签
    mark_tooltip = Column(String(100), comment="提示")  # 提示
    mark_shape = Column(String(20), comment="形状")  # 形状
    mark_color = Column(String(20), comment="颜色")  # 颜色
    dt = Column(DateTime, comment="添加时间")
    # 添加配置设置编码
    __table_args__ = {"mysql_collate": "utf8mb4_general_ci"}


class TableByTVMarksPrice(Base):
    # TV 图表的 mark 标记 (在价格主图的标记)
    __tablename__ = "cl_tv_marks_price"
    id = Column(Integer, primary_key=True, autoincrement=True)
    market = Column(String(20), comment="市场")  # 市场
    stock_code = Column(String(20), comment="标的代码")  # 标的代码
    stock_name = Column(String(100), comment="标的名称")  # 标的名称
    frequency = Column(String(10), default="", comment="展示周期")  # 展示周期
    mark_time = Column(Integer, comment="标签时间戳")  # 标签时间戳
    mark_color = Column(String(20), comment="颜色")  # 颜色
    mark_text = Column(String(100), comment="提示")  # 提示
    mark_label = Column(String(2), comment="标签")  # 标签
    mark_label_font_color = Column(String(20), comment="标签字体颜色")  # 标签字体颜色
    mark_min_size = Column(Integer, comment="最小尺寸")  # 最小尺寸

    dt = Column(DateTime, comment="添加时间")
    # 添加配置设置编码
    __table_args__ = {"mysql_collate": "utf8mb4_general_ci"}


class TableByOrder(Base):
    # 订单
    __tablename__ = "cl_order"
    id = Column(Integer, primary_key=True, autoincrement=True)
    market = Column(String(20), comment="市场")  # 市场
    stock_code = Column(String(20), comment="标的代码")  # 标的代码
    stock_name = Column(String(100), comment="标的名称")  # 标的名称
    order_type = Column(String(20), comment="订单类型")  # 订单类型
    order_price = Column(Float, comment="订单价格")  # 订单价格
    order_amount = Column(Float, comment="订单数量")  # 订单数量
    order_memo = Column(String(200), comment="订单备注")  # 订单备注
    dt = Column(DateTime, comment="添加时间")  # 添加时间
    # 添加配置设置编码
    __table_args__ = {"mysql_collate": "utf8mb4_general_ci"}


class TableByTVCharts(Base):
    # TV 图表的布局
    __tablename__ = "cl_tv_charts"
    id = Column(Integer, primary_key=True, autoincrement=True, comment="id")
    client_id = Column(String(50), comment="客户端id")
    user_id = Column(Integer, comment="用户id")
    chart_type = Column(String(20), comment="布局类型")
    symbol = Column(String(50), comment="标的")
    resolution = Column(String(20), comment="周期")
    content = Column(Text, comment="布局内容")
    timestamp = Column(Integer, comment="时间戳")
    name = Column(String(50), comment="布局名称")
    # 添加配置设置编码
    __table_args__ = {"mysql_collate": "utf8mb4_general_ci"}


class TableByAIAnalyse(Base):
    # AI 分析结果记录
    __tablename__ = "cl_ai_analyses"
    id = Column(Integer, primary_key=True, autoincrement=True)
    market = Column(String(20), comment="市场")  # 市场
    stock_code = Column(String(20), comment="标的")  # 标的
    stock_name = Column(String(100), comment="标的名称")  # 标的名称
    frequency = Column(String(10), comment="分析周期")
    dt = Column(DateTime, comment="分析时间")
    model = Column(String(100), comment="分析模型")
    prompt = Column(Text, comment="缠论当下说明")
    msg = Column(Text, comment="分析结果")

    # 添加配置设置编码
    __table_args__ = {"mysql_collate": "utf8mb4_general_ci"}


class TableByNews(Base):
    # 新闻数据表
    __tablename__ = "cl_news"
    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    news_id = Column(String(50), comment="新闻ID")  # 外部新闻ID
    story_id = Column(String(50), comment="故事ID")  # 故事ID
    title = Column(String(500), comment="新闻标题")  # 新闻标题
    body = Column(Text, comment="新闻内容")  # 新闻内容
    source = Column(String(100), comment="新闻来源")  # 新闻来源
    published_at = Column(DateTime, comment="发布时间")  # 发布时间
    language = Column(String(10), comment="语言", default="zh")  # 语言
    category = Column(String(50), comment="分类")  # 分类
    tags = Column(String(200), comment="标签")  # 标签
    sentiment_score = Column(Float, comment="情感分数")  # 情感分数
    importance_score = Column(Float, comment="重要性分数")  # 重要性分数
    created_at = Column(DateTime, comment="创建时间", default=datetime.datetime.now)  # 创建时间
    updated_at = Column(DateTime, comment="更新时间", default=datetime.datetime.now, onupdate=datetime.datetime.now)  # 更新时间
    
    # 添加配置设置编码
    __table_args__ = {"mysql_collate": "utf8mb4_general_ci"}


class TableByNewsAssetLink(Base):
    # 新闻资产关系表
    __tablename__ = "cl_news_asset_link"
    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    news_id = Column(String(50), index=True, comment="新闻ID")
    asset_code = Column(String(50), index=True, comment="资产代码")
    canonical_asset = Column(String(50), index=True, comment="标准资产代码")
    relation_type = Column(String(20), comment="关系类型 direct/driver/background")
    confidence = Column(Float, comment="置信度", default=0.5)
    reason = Column(String(200), comment="关联原因")
    matched_terms = Column(String(500), comment="命中的关键词")
    created_at = Column(DateTime, comment="创建时间", default=datetime.datetime.now)
    updated_at = Column(DateTime, comment="更新时间", default=datetime.datetime.now, onupdate=datetime.datetime.now)

    __table_args__ = (
        UniqueConstraint("news_id", "canonical_asset", "relation_type", name="uq_news_asset_relation"),
        {"mysql_collate": "utf8mb4_general_ci"},
    )


class TableByMarketSummary(Base):
    # 市场总结数据表
    __tablename__ = "cl_market_summary"
    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    title = Column(String(200), comment="总结标题")
    content = Column(Text, comment="总结内容")
    market = Column(String(20), comment="市场")
    code = Column(String(20), comment="标的代码")
    summary_type = Column(String(50), comment="总结类型", default="market_analysis")
    chart_snapshot = Column(Text, comment="图表快照HTML", nullable=True)
    created_at = Column(DateTime, comment="创建时间", default=datetime.datetime.now)
    updated_at = Column(DateTime, comment="更新时间", default=datetime.datetime.now, onupdate=datetime.datetime.now)
    
    # 添加配置设置编码
    __table_args__ = {"mysql_collate": "utf8mb4_general_ci"}


class TableBySerenityAIStocksLatestPrice(Base):
    __tablename__ = "cl_serenity_aistocks_latest_price"
    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    market = Column(String(20), nullable=False, comment="市场")
    code = Column(String(20), nullable=False, comment="规范化后的代码")
    symbol = Column(String(50), comment="原始展示代码")
    price = Column(Float, comment="最新价")
    rate = Column(Float, comment="涨跌幅")
    price_text = Column(String(50), comment="价格展示文本")
    rate_text = Column(String(50), comment="涨跌幅展示文本")
    status = Column(String(20), comment="状态 ok unsupported error", default="ok")
    source = Column(String(100), comment="数据来源")
    fetched_at = Column(DateTime, comment="行情抓取时间")
    created_at = Column(DateTime, comment="创建时间", default=datetime.datetime.now)
    updated_at = Column(DateTime, comment="更新时间", default=datetime.datetime.now, onupdate=datetime.datetime.now)

    __table_args__ = (
        UniqueConstraint("market", "code", name="table_serenity_aistocks_market_code_unique"),
        {"mysql_collate": "utf8mb4_general_ci"},
    )


class TableBySerenityAIStocksRecentThreeBuy(Base):
    __tablename__ = "cl_serenity_aistocks_recent_three_buy"
    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    market = Column(String(20), nullable=False, comment="市场")
    code = Column(String(20), nullable=False, comment="规范化后的代码")
    symbol = Column(String(50), comment="原始展示代码")
    recent_three_buy_time = Column(DateTime, comment="最近三买时间")
    recent_three_buy_time_text = Column(String(50), comment="最近三买展示文本")
    label = Column(String(50), comment="最近三买标签")
    status = Column(String(20), comment="状态 ok not_found unsupported error", default="ok")
    source = Column(String(100), comment="数据来源")
    scanned_at = Column(DateTime, comment="扫描时间")
    created_at = Column(DateTime, comment="创建时间", default=datetime.datetime.now)
    updated_at = Column(DateTime, comment="更新时间", default=datetime.datetime.now, onupdate=datetime.datetime.now)

    __table_args__ = (
        UniqueConstraint("market", "code", name="table_serenity_aistocks_recent_three_buy_market_code_unique"),
        {"mysql_collate": "utf8mb4_general_ci"},
    )


class TableByEconomicData(Base):
    # 经济数据表
    __tablename__ = "cl_economic_data"
    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    indicator_name = Column(String(200), comment="指标名称")  # 指标名称
    ds_mnemonic = Column(String(50), comment="数据源助记符")  # 数据源助记符
    latest_value = Column(Float, comment="最新值")  # 最新值
    latest_value_date = Column(String(20), comment="最新值日期")  # 最新值日期
    yoy_change_pct = Column(Float, comment="同比变化百分比")  # 同比变化百分比
    previous_value = Column(Float, comment="前值")  # 前值
    previous_value_date = Column(String(20), comment="前值日期")  # 前值日期
    previous_year_value = Column(Float, comment="去年同期值")  # 去年同期值
    year = Column(Integer, comment="年份")  # 年份
    units = Column(String(50), comment="单位")  # 单位
    source = Column(String(100), comment="数据来源")  # 数据来源
    created_at = Column(DateTime, comment="创建时间", default=datetime.datetime.now)  # 创建时间
    updated_at = Column(DateTime, comment="更新时间", default=datetime.datetime.now, onupdate=datetime.datetime.now)  # 更新时间
    
    # 添加配置设置编码
    __table_args__ = {"mysql_collate": "utf8mb4_general_ci"}


class TableByMarketEventFact(Base):
    __tablename__ = "cl_market_event_facts"
    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    event_uid = Column(String(64), nullable=False, unique=True, index=True, comment="事件唯一标识")
    event_type = Column(String(64), nullable=False, index=True, comment="事件类型")
    asset_class = Column(String(32), nullable=True, index=True, comment="资产分类")
    region = Column(String(64), nullable=True, index=True, comment="区域")
    symbol = Column(String(64), nullable=True, index=True, comment="标的代码")
    title = Column(String(255), nullable=False, comment="事件标题")
    source_name = Column(String(100), nullable=False, index=True, comment="数据来源")
    importance_score = Column(Float, nullable=True, comment="重要度")
    actual_value = Column(Float, nullable=True, comment="实际值")
    forecast_value = Column(Float, nullable=True, comment="预期值")
    previous_value = Column(Float, nullable=True, comment="前值")
    surprise_value = Column(Float, nullable=True, comment="预期差")
    published_at = Column(DateTime, nullable=True, index=True, comment="发布时间")
    effective_at = Column(DateTime, nullable=True, comment="生效时间")
    payload_json = Column(Text, nullable=True, comment="原始内容")
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.datetime.now, onupdate=datetime.datetime.now)
    __table_args__ = {"mysql_collate": "utf8mb4_general_ci"}


class TableByMarketFactorSnapshot(Base):
    __tablename__ = "cl_market_factor_snapshots"
    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    snapshot_uid = Column(String(64), nullable=False, unique=True, index=True, comment="快照唯一标识")
    factor_group = Column(String(64), nullable=False, index=True, comment="因子组")
    factor_name = Column(String(128), nullable=False, index=True, comment="因子名")
    asset_class = Column(String(32), nullable=True, index=True, comment="资产分类")
    symbol = Column(String(64), nullable=True, index=True, comment="标的代码")
    tenor = Column(String(32), nullable=True, index=True, comment="期限")
    value = Column(Float, nullable=True, comment="数值")
    unit = Column(String(32), nullable=True, comment="单位")
    change_1d = Column(Float, nullable=True, comment="1日变化")
    change_5d = Column(Float, nullable=True, comment="5日变化")
    zscore_60d = Column(Float, nullable=True, comment="60日标准分")
    source_name = Column(String(100), nullable=False, index=True, comment="数据来源")
    as_of_time = Column(DateTime, nullable=False, index=True, comment="快照时间")
    metadata_json = Column(Text, nullable=True, comment="扩展字段")
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.datetime.now, onupdate=datetime.datetime.now)
    __table_args__ = {"mysql_collate": "utf8mb4_general_ci"}


class TableByMarketStructureMetric(Base):
    __tablename__ = "cl_market_structure_metrics"
    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    metric_uid = Column(String(64), nullable=False, unique=True, index=True, comment="结构指标唯一标识")
    asset_class = Column(String(32), nullable=True, index=True, comment="资产分类")
    symbol = Column(String(64), nullable=True, index=True, comment="标的代码")
    metric_name = Column(String(128), nullable=False, index=True, comment="指标名称")
    metric_value = Column(Float, nullable=True, comment="指标数值")
    window = Column(String(32), nullable=True, comment="窗口")
    cross_section_rank = Column(Float, nullable=True, comment="横截面排名")
    source_name = Column(String(100), nullable=False, index=True, comment="数据来源")
    as_of_time = Column(DateTime, nullable=False, index=True, comment="指标时间")
    metadata_json = Column(Text, nullable=True, comment="扩展字段")
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.datetime.now, onupdate=datetime.datetime.now)
    __table_args__ = {"mysql_collate": "utf8mb4_general_ci"}


class TableByAgentInferenceLog(Base):
    __tablename__ = "cl_agent_inference_logs"
    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    run_id = Column(String(80), nullable=False, index=True, comment="推演运行ID")
    agent_name = Column(String(80), nullable=False, index=True, comment="Agent名称")
    asset_class = Column(String(32), nullable=True, index=True, comment="资产分类")
    symbol = Column(String(64), nullable=True, index=True, comment="标的代码")
    question = Column(Text, nullable=True, comment="问题")
    thesis = Column(Text, nullable=True, comment="结论")
    confidence_before = Column(Float, nullable=True, comment="结论前置信度")
    confidence_after = Column(Float, nullable=True, comment="结论后置信度")
    used_event_ids = Column(Text, nullable=True, comment="使用事件ID")
    used_factor_ids = Column(Text, nullable=True, comment="使用因子ID")
    changed_conclusion = Column(String(16), nullable=True, comment="是否改变结论")
    metadata_json = Column(Text, nullable=True, comment="扩展字段")
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.now, index=True)
    __table_args__ = {"mysql_collate": "utf8mb4_general_ci"}


class TableByEventPriceReaction(Base):
    __tablename__ = "cl_event_price_reactions"
    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    reaction_uid = Column(String(64), nullable=False, unique=True, index=True, comment="验证唯一标识")
    event_uid = Column(String(64), nullable=False, index=True, comment="事件唯一标识")
    symbol = Column(String(64), nullable=False, index=True, comment="标的代码")
    frequency = Column(String(16), nullable=False, index=True, comment="频率")
    return_30m_pct = Column(Float, nullable=True, comment="30分钟收益")
    return_120m_pct = Column(Float, nullable=True, comment="120分钟收益")
    return_1d_pct = Column(Float, nullable=True, comment="1日收益")
    return_5d_pct = Column(Float, nullable=True, comment="5日收益")
    direction_aligned = Column(Integer, nullable=True, comment="方向一致")
    reaction_label = Column(String(32), nullable=True, comment="验证标签")
    validated_at = Column(DateTime, nullable=True, index=True, comment="验证时间")
    metadata_json = Column(Text, nullable=True, comment="扩展字段")
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.datetime.now, onupdate=datetime.datetime.now)
    __table_args__ = {"mysql_collate": "utf8mb4_general_ci"}


def _to_datetime_value(value: Any) -> Optional[datetime.datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime.datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, datetime.date):
        return datetime.datetime.combine(value, datetime.time.min)
    try:
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            return None
        if hasattr(parsed, "to_pydatetime"):
            parsed = parsed.to_pydatetime()
        if isinstance(parsed, datetime.datetime):
            return parsed.replace(tzinfo=None)
    except Exception:
        return None
    return None


def _to_float_value(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    try:
        return float(value)
    except Exception:
        return None


def _to_json_text(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return str(value)


def _build_uid(prefix: str, payload: Dict[str, Any]) -> str:
    normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.md5(f"{prefix}:{normalized}".encode("utf-8")).hexdigest()


@fun.singleton
class DB(object):
    global Base

    def __init__(self) -> None:
        if config.DB_TYPE == "sqlite":
            db_path = get_data_path() / "db"
            if db_path.is_dir() is False:
                db_path.mkdir(parents=True)
            self.engine = create_engine(
                f"sqlite:///{str(db_path / f'{config.DB_DATABASE}.sqlite')}",
                echo=False,
                poolclass=QueuePool,
                pool_size=10,
                max_overflow=20,
                pool_timeout=10,
            )
        elif config.DB_TYPE == "mysql":
            self.engine = create_engine(
                f"mysql+pymysql://{config.DB_USER}:{config.DB_PWD}@{config.DB_HOST}:{config.DB_PORT}/{config.DB_DATABASE}?charset=utf8mb4",
                echo=False,
                poolclass=QueuePool,
                pool_recycle=3600,
                pool_pre_ping=True,
                pool_size=10,
                max_overflow=20,
                pool_timeout=10,
            )
        else:
            raise Exception("DB_TYPE 配置错误")

        self.Session = sessionmaker(bind=self.engine)

        self.__news_asset_table_ready = True
        try:
            Base.metadata.create_all(self.engine)
        except OperationalError as e:
            if "readonly" in str(e).lower() or "read-only" in str(e).lower():
                self.__news_asset_table_ready = False
                print(f"DB create_all skipped in readonly mode: {e}")
            else:
                raise

        self.__cache_tables = {}

    def klines_tables(self, market: str, stock_code: str):
        stock_code = (
            stock_code.replace(".", "_")
            .replace("-", "_")
            .replace("/", "_")
            .replace("@", "_")
            .lower()
        )
        if market == Market.HK.value:
            table_name = f"{market}_klines_{stock_code[-3:]}"
        elif market == Market.A.value:
            table_name = f"{market}_klines_{stock_code[:7]}"
        elif market == Market.US.value:
            table_name = f"{market}_klines_{stock_code[0]}"
        elif market == Market.FX.value:
            table_name = f"{market}_klines_{stock_code}"
        elif market == Market.CURRENCY.value:
            table_name = f"{market}_klines_{stock_code}"
        elif market == Market.CURRENCY_SPOT.value:
            table_name = f"{market}_klines_{stock_code}"
        elif market == Market.FUTURES.value:
            table_name = f"{market}_klines_{stock_code}"
        else:
            raise Exception(f"市场错误：{market}")

        if table_name in self.__cache_tables:
            return self.__cache_tables[table_name]

        class TableByKlines(Base):
            # 表名
            __tablename__ = table_name
            __table_args__ = (
                UniqueConstraint("code", "dt", "f", name="table_code_dt_f_unique"),
            )
            # 表结构
            code = Column(String(20), primary_key=True, comment="标的代码")
            dt = Column(DateTime, primary_key=True, comment="日期")
            f = Column(String(5), primary_key=True, comment="周期")
            o = Column(Float)
            c = Column(Float)
            h = Column(Float)
            l = Column(Float)
            v = Column(Float)
            # 添加配置设置编码
            __table_args__ = {
                "mysql_collate": "utf8mb4_general_ci",
            }

        if market == Market.FUTURES.value:
            # 期货市场，添加持仓列
            TableByKlines.p = Column(Float, comment="持仓量")

        self.__cache_tables[table_name] = TableByKlines
        Base.metadata.create_all(self.engine)
        return TableByKlines

    def klines_query(
        self,
        market: str,
        code: str,
        frequency: str,
        start_date: datetime.datetime = None,
        end_date: datetime.datetime = None,
        limit: int = 5000,
        order: str = "desc",
    ) -> List:
        """
        获取k线数据
        :param market:
        :param code:
        :param frequency:
        :param start_date:
        :param end_date:
        :param limit:
        :param order:
        :return:
        """
        with self.Session() as session:
            table = self.klines_tables(market, code)
            # 查询数据库
            filter = (table.code == code, table.f == frequency)
            if start_date is not None:
                filter += (table.dt >= start_date,)
            if end_date is not None:
                filter += (table.dt <= end_date,)
            query = session.query(table).filter(*filter)
            if order == "desc":
                query = query.order_by(table.dt.desc())
            else:
                query = query.order_by(table.dt.asc())
            if limit is not None:
                query = query.limit(limit)
            return query.all()

    def klines_last_datetime(self, market, code, frequency):
        """
        查询k线表中最后一条记录的日期
        :param market:
        :param code:
        :param frequency:
        :return:
        """
        with self.Session() as session:
            table = self.klines_tables(market, code)
            last_date = (
                session.query(table.dt)
                .filter(table.code == code)
                .filter(table.f == frequency)
                .order_by(table.dt.desc())
                .first()
            )
            if last_date is None:
                return None
            if market == "a":
                return last_date[0].strftime("%Y-%m-%d")
            else:
                return last_date[0].strftime("%Y-%m-%d %H:%M:%S")

    def klines_insert(
        self, market: str, code: str, frequency: str, klines: pd.DataFrame
    ):
        """
        插入k线
        :param market:
        :param code:
        :param frequency:
        :param klines:
        :return:
        """
        with self.Session() as session:
            table = self.klines_tables(market, code)

            # 如果是 sqlite ，则慢慢更新吧
            if config.DB_TYPE == "sqlite":
                for _, _k in klines.iterrows():
                    _in_k = {
                        "code": code,
                        "f": frequency,
                        "dt": _k["date"].replace(tzinfo=None),  # 去除时区信息
                        "o": _k["open"],
                        "c": _k["close"],
                        "h": _k["high"],
                        "l": _k["low"],
                        "v": _k["volume"],
                    }
                    if "position" in _k.keys():
                        _in_k["p"] = _k["position"]
                    db_k = (
                        session.query(table)
                        .filter(
                            table.code == code,
                            table.f == frequency,
                            table.dt == _in_k["dt"],
                        )
                        .first()
                    )
                    if db_k is None:
                        session.add(table(**_in_k))
                    else:
                        session.query(table).filter(
                            table.code == code,
                            table.f == frequency,
                            table.dt == _in_k["dt"],
                        ).update(_in_k)
                session.commit()
                return True

            # 将 klines 数据拆分为每 500 条一组，批量插入
            group = np.arange(len(klines)) // 500
            groups = [
                group.reset_index(drop=True) for _, group in klines.groupby(group)
            ]
            in_position = "position" in klines.columns
            for g_klines in groups:
                insert_klines = []
                for _, _k in g_klines.iterrows():
                    _insert_k = {
                        "code": code,
                        "dt": _k["date"].replace(tzinfo=None),  # 去除时区信息
                        "f": frequency,
                        "o": _k["open"],
                        "c": _k["close"],
                        "h": _k["high"],
                        "l": _k["low"],
                        "v": _k["volume"],
                    }
                    if in_position:
                        _insert_k["p"] = _k["position"]
                    insert_klines.append(_insert_k)
                insert_stmt = insert(table).values(insert_klines)
                update_keys = ["o", "c", "h", "l", "v"]
                if in_position:
                    update_keys.append("p")
                update_columns = {
                    x.name: x for x in insert_stmt.inserted if x.name in update_keys
                }
                upsert_stmt = insert_stmt.on_duplicate_key_update(**update_columns)
                session.execute(upsert_stmt)
                session.commit()

        return True

    def klines_delete(
        self,
        market: str,
        code: str,
        frequency: str = None,
        dt: datetime.datetime = None,
    ):
        """
        删除k线
        :param market:
        :param code:
        :param frequency:
        :param dt:
        :return:
        """
        with self.Session() as session:
            table = self.klines_tables(market, code)
            q = session.query(table).filter(table.code == code)
            if frequency is not None:
                q = q.filter(table.f == frequency)
            if dt is not None:
                q = q.filter(table.dt == dt)
            q.delete()
            session.commit()

        return True

    def zx_get_groups(self, market: str) -> List[TableByZxGroup]:
        """
        获取自选分组
        """
        with self.Session() as session:
            return (
                session.query(TableByZxGroup)
                .filter(TableByZxGroup.market == market)
                .order_by(TableByZxGroup.add_dt.asc())
                .all()
            )

    def zx_add_group(self, market: str, zx_group: str) -> bool:
        """
        添加自选分组
        """
        with self.Session() as session:
            session.add(
                TableByZxGroup(
                    market=market, zx_group=zx_group, add_dt=datetime.datetime.now()
                )
            )
            session.commit()

        return True

    def zx_del_group(self, market: str, zx_group: str) -> bool:
        """
        删除自选分组
        """
        with self.Session() as session:
            session.query(TableByZxGroup).filter(
                TableByZxGroup.market == market, TableByZxGroup.zx_group == zx_group
            ).delete()
            session.commit()

        return True

    def zx_get_group_stocks(self, market: str, zx_group: str) -> List[TableByZixuan]:
        """
        获取自选组下的股票列表
        """
        with self.Session() as session:
            stocks = (
                session.query(TableByZixuan)
                .filter(TableByZixuan.zx_group == zx_group)
                .filter(TableByZixuan.market == market)
                .order_by(TableByZixuan.position.asc())
                .all()
            )
        return stocks

    def zx_add_group_stock(
        self,
        market: str,
        zx_group: str,
        stock_code: str,
        stock_name: str,
        memo: str = "",
        color: str = "",
        location: str = "bottom",
    ):
        with self.Session() as session:
            # 添加前，统一删除在自选组下的股票信息
            session.query(TableByZixuan).filter(
                TableByZixuan.market == market,
                TableByZixuan.zx_group == zx_group,
                TableByZixuan.stock_code == stock_code,
            ).delete()

            position = 0
            if location == "top":
                # 自选组的股票位置+1
                session.query(TableByZixuan).filter(
                    TableByZixuan.zx_group == zx_group
                ).update(
                    {TableByZixuan.position: TableByZixuan.position + 1},
                    synchronize_session=False,
                )
            else:
                # 获取自选组的 position 最大值
                max_position = (
                    session.query(func.max(TableByZixuan.position))
                    .filter(TableByZixuan.market == market)
                    .filter(TableByZixuan.zx_group == zx_group)
                    .scalar()
                )
                position = max_position + 1 if max_position is not None else 0
            zx_stock = TableByZixuan(
                market=market,
                zx_group=zx_group,
                stock_code=stock_code,
                stock_name=stock_name,
                stock_color=color,
                position=position,
                stock_memo=memo,
                add_datetime=datetime.datetime.now(),
            )
            session.add(zx_stock)
            session.commit()

        return True

    def zx_del_group_stock(self, market: str, zx_group: str, stock_code: str):
        with self.Session() as session:
            session.query(TableByZixuan).filter(TableByZixuan.market == market).filter(
                TableByZixuan.zx_group == zx_group
            ).filter(TableByZixuan.stock_code == stock_code).delete()
            session.commit()

        return True

    def zx_update_stock_color(
        self, market: str, zx_group: str, stock_code: str, color: str
    ):
        with self.Session() as session:
            session.query(TableByZixuan).filter(TableByZixuan.market == market).filter(
                TableByZixuan.zx_group == zx_group
            ).filter(TableByZixuan.stock_code == stock_code).update(
                {"stock_color": color}, synchronize_session=False
            )
            session.commit()

        return True

    def zx_update_stock_name(
        self, market: str, zx_group: str, stock_code: str, stock_name: str
    ):
        with self.Session() as session:
            session.query(TableByZixuan).filter(TableByZixuan.market == market).filter(
                TableByZixuan.zx_group == zx_group
            ).filter(TableByZixuan.stock_code == stock_code).update(
                {"stock_name": stock_name}, synchronize_session=False
            )
            session.commit()

        return True

    def zx_stock_sort_top(self, market: str, zx_group: str, stock_code: str):
        with self.Session() as session:
            # market、zx_group 结果下的 position + 1
            session.query(TableByZixuan).filter(TableByZixuan.market == market).filter(
                TableByZixuan.zx_group == zx_group
            ).update(
                {"position": TableByZixuan.position + 1}, synchronize_session=False
            )
            # 再将指定的股票 postition 更新为 0
            session.query(TableByZixuan).filter(TableByZixuan.market == market).filter(
                TableByZixuan.zx_group == zx_group
            ).filter(TableByZixuan.stock_code == stock_code).update(
                {"position": 0}, synchronize_session=False
            )
            session.commit()

        return True

    def zx_stock_sort_bottom(self, market: str, zx_group: str, stock_code: str):
        with self.Session() as session:
            # 获取 market zx_group 结果下最大的position
            max_position = (
                session.query(func.max(TableByZixuan.position))
                .filter(TableByZixuan.market == market)
                .filter(TableByZixuan.zx_group == zx_group)
                .scalar()
            )
            # 将 market zx_group stock_code 结果下的 position 更新为 max_position + 1
            session.query(TableByZixuan).filter(TableByZixuan.market == market).filter(
                TableByZixuan.zx_group == zx_group
            ).filter(TableByZixuan.stock_code == stock_code).update(
                {"position": max_position + 1}, synchronize_session=False
            )
            session.commit()

        return True

    def zx_clear_by_group(self, market: str, zx_group: str):
        with self.Session() as session:
            # 删除 market、zx_group 下所有的记录
            session.query(TableByZixuan).filter(TableByZixuan.market == market).filter(
                TableByZixuan.zx_group == zx_group
            ).delete(synchronize_session=False)
            session.commit()

        return True

    def zx_query_group_by_code(self, market: str, stock_code: str) -> List[str]:
        with self.Session() as session:
            # 查询 market 下 stock_code 的所有去重的 zx_group 记录
            return [
                _[0]
                for _ in (
                    session.query(TableByZixuan.zx_group)
                    .filter(TableByZixuan.market == market)
                    .filter(TableByZixuan.stock_code == stock_code)
                    .distinct()
                    .all()
                )
            ]

    def order_save(
        self,
        market: str,
        stock_code: str,
        stock_name: str,
        order_type: str,
        order_price: float,
        order_amount: float,
        order_memo: str,
        order_time: Union[str, datetime.datetime],
    ):
        with self.Session() as session:
            # 保存订单
            order = TableByOrder(
                market=market,
                stock_code=stock_code,
                stock_name=stock_name,
                order_type=order_type,
                order_price=order_price,
                order_amount=order_amount,
                order_memo=order_memo,
                dt=order_time,
            )
            session.add(order)
            session.commit()

        return True

    def order_query_by_code(self, market: str, stock_code: str) -> List[TableByOrder]:
        with self.Session() as session:
            # 查询 market 下 stock_code 的所有订单
            orders = (
                session.query(TableByOrder)
                .filter(TableByOrder.market == market)
                .filter(TableByOrder.stock_code == stock_code)
                .all()
            )

        # {
        #     "code": "SH.000001",
        #     "datetime": "2021-10-19 10:09:51",
        #     "type": "buy", (允许的值：buy 买入 sell 卖出  open_long 开多  close_long 平多 open_short 开空 close_short 平空)
        #     "price": 205.8,
        #     "amount": 300.0,
        #     "info": "涨涨涨"
        # }
        return [  # 兼容之前的
            {
                "code": _o.stock_code,
                "name": _o.stock_name,
                "datetime": _o.dt,
                "type": _o.order_type,
                "price": _o.order_price,
                "amount": _o.order_amount,
                "info": _o.order_memo,
            }
            for _o in orders
        ]

    def order_clear_by_code(self, market: str, stock_code: str):
        with self.Session() as session:
            # 清除 market 下 stock_code 的所有订单
            session.query(TableByOrder).filter(TableByOrder.market == market).filter(
                TableByOrder.stock_code == stock_code
            ).delete()
            session.commit()

        return True

    def task_save(
        self,
        market: str,
        task_name: str,
        zx_group: str,
        frequency: str,
        interval_minutes: int,
        check_bi_type: str,
        check_bi_beichi: str,
        check_bi_mmd: str,
        check_xd_type: str,
        check_xd_beichi: str,
        check_xd_mmd: str,
        check_idx_ma_info: str,
        check_idx_macd_info: str,
        is_run: int,
        is_send_msg: int,
    ):
        with self.Session() as session:
            # 保存任务
            session.add(
                TableByAlertTask(
                    market=market,
                    task_name=task_name,
                    zx_group=zx_group,
                    frequency=frequency,
                    interval_minutes=interval_minutes,
                    check_bi_type=check_bi_type,
                    check_bi_beichi=check_bi_beichi,
                    check_bi_mmd=check_bi_mmd,
                    check_xd_type=check_xd_type,
                    check_xd_beichi=check_xd_beichi,
                    check_xd_mmd=check_xd_mmd,
                    check_idx_ma_info=check_idx_ma_info,
                    check_idx_macd_info=check_idx_macd_info,
                    is_run=is_run,
                    is_send_msg=is_send_msg,
                    dt=datetime.datetime.now(),
                )
            )
            session.commit()

        return True

    def task_query(self, market: str = None, id: int = None) -> List[TableByAlertTask]:
        with self.Session() as session:
            # 查询任务
            query = session.query(TableByAlertTask)
            filter = ()
            if market is not None:
                filter += (TableByAlertTask.market == market,)
            if id is not None:
                filter += (TableByAlertTask.id == id,)
            if len(filter) > 0:
                return query.filter(*filter).all()
            return query.all()

    def task_delete(self, id: int):
        with self.Session() as session:
            # 删除任务
            session.query(TableByAlertTask).filter(TableByAlertTask.id == id).delete()
            session.commit()

        return True

    def task_update(
        self,
        id: int,
        market: str,
        task_name: str,
        zx_group: str,
        frequency: str,
        interval_minutes: int,
        check_bi_type: str,
        check_bi_beichi: str,
        check_bi_mmd: str,
        check_xd_type: str,
        check_xd_beichi: str,
        check_xd_mmd: str,
        check_idx_ma_info: str,
        check_idx_macd_info: str,
        is_run: int,
        is_send_msg: int,
    ):
        with self.Session() as session:
            session.query(TableByAlertTask).filter(
                TableByAlertTask.market == market,
                TableByAlertTask.id == id,
            ).update(
                {
                    TableByAlertTask.task_name: task_name,
                    TableByAlertTask.zx_group: zx_group,
                    TableByAlertTask.frequency: frequency,
                    TableByAlertTask.interval_minutes: interval_minutes,
                    TableByAlertTask.check_bi_type: check_bi_type,
                    TableByAlertTask.check_bi_beichi: check_bi_beichi,
                    TableByAlertTask.check_bi_mmd: check_bi_mmd,
                    TableByAlertTask.check_xd_type: check_xd_type,
                    TableByAlertTask.check_xd_beichi: check_xd_beichi,
                    TableByAlertTask.check_xd_mmd: check_xd_mmd,
                    TableByAlertTask.check_idx_ma_info: check_idx_ma_info,
                    TableByAlertTask.check_idx_macd_info: check_idx_macd_info,
                    TableByAlertTask.is_run: is_run,
                    TableByAlertTask.is_send_msg: is_send_msg,
                    TableByAlertTask.dt: datetime.datetime.now(),
                }
            )
            session.commit()
        return True

    def alert_record_save(
        self,
        market: str,
        task_name: str,
        stock_code: str,
        stock_name: str,
        frequency: str,
        alert_msg: str,
        bi_is_done: str,
        bi_is_td: str,
        line_type: str,
        line_dt: datetime.datetime,
    ):
        """
        保存预警记录
        :param market:
        :param stock_code:
        :param stock_name:
        :param frequency:
        :param alert_msg:
        :param bi_is_down:
        :param bi_is_td:
        :param line_dt:
        :return:
        """
        with self.Session() as session:
            recored = TableByAlertRecord(
                market=market,
                task_name=task_name,
                stock_code=stock_code,
                stock_name=stock_name,
                frequency=frequency,
                alert_msg=alert_msg,
                bi_is_done=bi_is_done,
                bi_is_td=bi_is_td,
                line_type=line_type,
                line_dt=line_dt.replace(tzinfo=None),
                alert_dt=datetime.datetime.now(),
            )
            session.add(recored)
            session.commit()

        return True

    def alert_record_query_by_code(
        self,
        market: str,
        stock_code: str,
        frequency: str,
        line_type: str,
        line_dt: datetime.datetime,
    ) -> TableByAlertRecord:
        """
        查询预警记录
        :param market:
        :param stock_code:
        :param frequency:
        :param dt:
        :return:
        """
        with self.Session() as session:
            return (
                session.query(TableByAlertRecord)
                .filter(
                    TableByAlertRecord.market == market,
                    TableByAlertRecord.stock_code == stock_code,
                    TableByAlertRecord.frequency == frequency,
                    TableByAlertRecord.line_type == line_type,
                    TableByAlertRecord.line_dt == line_dt,
                )
                .order_by(TableByAlertRecord.alert_dt.desc())
                .first()
            )

    def alert_record_query(
        self, market: str, task_name: str = None
    ) -> List[TableByAlertRecord]:
        """
        查询预警记录
        :param market:
        :param stock_code:
        :param frequency:
        :param dt:
        :return:
        """
        with self.Session() as session:
            query = session.query(TableByAlertRecord)
            query = query.filter(TableByAlertRecord.market == market)
            if task_name:
                query = query.filter(TableByAlertRecord.task_name == task_name)
            return query.order_by(TableByAlertRecord.alert_dt.desc()).limit(100)

    def marks_add(
        self,
        market: str,
        stock_code: str,
        stock_name: str,
        frequency: str,
        mark_time: int,
        mark_label: str,
        mark_tooltip: str,
        mark_shape: str,
        mark_color: str,
    ):
        """
        添加代码在 tv 时间轴显示的信息
        :param market:
        :param stock_code:
        :param stock_name:
        :param frequency:   需要在什么周期显示，默认 ‘’，所有周期，可以是 'd', '30m', '5m' 这样之下指定周期下展示
        :param mark_time:   int 时间戳
        :param mark_label:  时间刻度标记的标签，英文字母，最大 两位
        :param mark_tooltip:    工具提示内容
        :param mark_shape:  "circle" | "earningUp" | "earningDown" | "earning" 形状
        :param mark_color: 颜色 rgb，比如 'red'  '#FF0000'
        :return:
        """
        with self.Session() as session:
            # 相同的 market,code/mark_time/mark_label 只能又一个，先删除一下
            session.query(TableByTVMarks).filter(
                TableByTVMarks.market == market,
                TableByTVMarks.stock_code == stock_code,
                TableByTVMarks.mark_time == mark_time,
                TableByTVMarks.mark_label == mark_label,
            ).delete()

            mark = TableByTVMarks(
                market=market,
                stock_code=stock_code,
                stock_name=stock_name,
                frequency=frequency,
                mark_time=mark_time,
                mark_label=mark_label,
                mark_tooltip=mark_tooltip,
                mark_shape=mark_shape,
                mark_color=mark_color,
                dt=datetime.datetime.now(),
            )
            session.add(mark)
            session.commit()

        return True

    def marks_query(
        self, market: str, stock_code: str, start_date: int = None
    ) -> List[TableByTVMarks]:
        """
        查询图表标记
        :param market:
        :param stock_code:
        :return:
        """
        with self.Session() as session:
            query = session.query(TableByTVMarks).filter(
                TableByTVMarks.market == market,
                TableByTVMarks.stock_code == stock_code,
            )
            if start_date is not None:
                query = query.filter(TableByTVMarks.mark_time >= start_date)

            return query.order_by(TableByTVMarks.mark_time.asc()).all()

    def marks_del(self, market: str, mark_label: str):
        with self.Session() as session:
            session.query(TableByTVMarks).filter(
                TableByTVMarks.market == market, TableByTVMarks.mark_label == mark_label
            ).delete()
            session.commit()

        return True

    def marks_add_by_price(
        self,
        market: str,
        stock_code: str,
        stock_name: str,
        frequency: str,
        mark_time: int,
        mark_label: str,
        mark_text: str,
        mark_label_color: str,
        mark_color: str,
    ):
        """
        添加代码在 tv 价格主图显示的信息
        """
        with self.Session() as session:
            # 相同的 market,code/mark_time/mark_label 只能有一个，先删除一下
            session.query(TableByTVMarks).filter(
                TableByTVMarks.market == market,
                TableByTVMarks.stock_code == stock_code,
                TableByTVMarks.mark_time == mark_time,
                TableByTVMarks.mark_label == mark_label,
            ).delete()

            mark = TableByTVMarksPrice(
                market=market,
                stock_code=stock_code,
                stock_name=stock_name,
                frequency=frequency,
                mark_time=mark_time,
                mark_color=mark_color,
                mark_text=mark_text,
                mark_label=mark_label,
                mark_label_font_color=mark_label_color,
                mark_min_size=1,
                dt=datetime.datetime.now(),
            )
            session.add(mark)
            session.commit()

        return True

    def marks_query_by_price(
        self, market: str, stock_code: str, start_date: int = None
    ) -> List[TableByTVMarksPrice]:
        """
        查询图表标记
        :param market:
        :param stock_code:
        :return:
        """
        with self.Session() as session:
            query = session.query(TableByTVMarksPrice).filter(
                TableByTVMarksPrice.market == market,
                TableByTVMarksPrice.stock_code == stock_code,
            )
            if start_date is not None:
                query = query.filter(TableByTVMarksPrice.mark_time >= start_date)
            return query.order_by(TableByTVMarksPrice.mark_time.asc()).all()

    def marks_del_by_price(self, market: str, mark_label: str):
        with self.Session() as session:
            session.query(TableByTVMarksPrice).filter(
                TableByTVMarks.market == market,
                TableByTVMarksPrice.mark_label == mark_label,
            ).delete()
            session.commit()

        return True

    def marks_del_all_by_code(self, market: str, code: str):
        """
        删除代码的所有标记
        """
        with self.Session() as session:
            session.query(TableByTVMarks).filter(
                TableByTVMarks.market == market,
                TableByTVMarks.stock_code == code,
            ).delete()
            session.query(TableByTVMarksPrice).filter(
                TableByTVMarksPrice.market == market,
                TableByTVMarksPrice.stock_code == code,
            ).delete()
            session.commit()
        return True

    def tv_chart_list(self, chart_type, client_id, user_id):
        with self.Session() as session:
            return (
                session.query(TableByTVCharts)
                .filter(
                    TableByTVCharts.chart_type == chart_type,
                    TableByTVCharts.client_id == client_id,
                    TableByTVCharts.user_id == user_id,
                )
                .all()
            )

    def tv_chart_save(
        self, chart_type, client_id, user_id, name, content, symbol, resolution
    ):
        # 保存图表布局，并返回 id
        with self.Session() as session:
            chart = TableByTVCharts(
                chart_type=chart_type,
                client_id=client_id,
                user_id=user_id,
                name=name,
                content=content,
                symbol=symbol,
                resolution=resolution,
                timestamp=int(time.time()),
            )
            session.add(chart)
            session.commit()
            return chart.id

    def tv_chart_update(
        self, chart_type, id, client_id, user_id, name, content, symbol, resolution
    ):
        # 更新图表布局
        with self.Session() as session:
            session.query(TableByTVCharts).filter(
                TableByTVCharts.id == id,
                TableByTVCharts.client_id == client_id,
                TableByTVCharts.user_id == user_id,
                TableByTVCharts.chart_type == chart_type,
            ).update(
                {
                    TableByTVCharts.name: name,
                    TableByTVCharts.content: content,
                    TableByTVCharts.symbol: symbol,
                    TableByTVCharts.resolution: resolution,
                    TableByTVCharts.timestamp: int(time.time()),
                }
            )
            session.commit()
        return True

    def tv_chart_get(self, chart_type, id, client_id, user_id):
        # 获取图表布局
        with self.Session() as session:
            return (
                session.query(TableByTVCharts)
                .filter(
                    TableByTVCharts.id == id,
                    TableByTVCharts.chart_type == chart_type,
                    TableByTVCharts.client_id == client_id,
                    TableByTVCharts.user_id == user_id,
                )
                .first()
            )

    def tv_chart_get_by_name(self, chart_type, name, client_id, user_id):
        # 获取图表布局
        with self.Session() as session:
            return (
                session.query(TableByTVCharts)
                .filter(
                    TableByTVCharts.name == name,
                    TableByTVCharts.chart_type == chart_type,
                    TableByTVCharts.client_id == client_id,
                    TableByTVCharts.user_id == user_id,
                )
                .first()
            )

    def tv_chart_del(self, chart_type, id, client_id, user_id):
        # 删除图表布局
        with self.Session() as session:
            session.query(TableByTVCharts).filter(
                TableByTVCharts.id == id,
                TableByTVCharts.chart_type == chart_type,
                TableByTVCharts.client_id == client_id,
                TableByTVCharts.user_id == user_id,
            ).delete()
            session.commit()
        return True

    def tv_chart_del_by_name(self, chart_type, name, client_id, user_id):
        # 根据名称删除图表布局
        with self.Session() as session:
            session.query(TableByTVCharts).filter(
                TableByTVCharts.name == name,
                TableByTVCharts.chart_type == chart_type,
                TableByTVCharts.client_id == client_id,
                TableByTVCharts.user_id == user_id,
            ).delete()
            session.commit()
        return True

    def cache_get(self, key: str):
        with self.Session() as session:
            # 获取当前时间戳
            now = int(time.time())
            # 获取缓存数据
            cache = session.query(TableByCache).filter(TableByCache.k == key).first()
            # 缓存数据存在，且缓存数据未过期
            if cache and (cache.expire == 0 or cache.expire > now):
                return json.loads(cache.v)
            # 缓存数据不存在，或缓存数据已过期
            # 删除过期缓存数据，expire_time != 0 and expire_time < now
            session.query(TableByCache).filter(
                TableByCache.expire != 0, TableByCache.expire < now
            ).delete()
            session.commit()

        return None

    def cache_set(self, key: str, val: dict, expire: int = 0):
        with self.Session() as session:
            session.query(TableByCache).filter(TableByCache.k == key).delete()
            cache = TableByCache(k=key, v=json.dumps(val), expire=expire)
            session.add(cache)
            session.commit()

        return True

    def cache_del(self, key: str):
        with self.Session() as session:
            session.query(TableByCache).filter(TableByCache.k == key).delete()
            session.commit()

        return True

    def serenity_aistocks_latest_prices_replace(self, rows: List[dict]) -> bool:
        with self.Session() as session:
            now = datetime.datetime.now()
            for row in rows or []:
                market, code = _normalize_serenity_aistocks_market_code(
                    row.get("market"), row.get("code")
                )
                if not market or not code:
                    continue

                existing = (
                    session.query(TableBySerenityAIStocksLatestPrice)
                    .filter(
                        TableBySerenityAIStocksLatestPrice.market == market,
                        TableBySerenityAIStocksLatestPrice.code == code,
                    )
                    .first()
                )

                payload = {
                    "market": market,
                    "code": code,
                    "symbol": row.get("symbol"),
                    "price": row.get("price"),
                    "rate": row.get("rate"),
                    "price_text": row.get("price_text"),
                    "rate_text": row.get("rate_text"),
                    "status": row.get("status", "ok"),
                    "source": row.get("source"),
                    "fetched_at": row.get("fetched_at"),
                    "updated_at": row.get("updated_at") or now,
                }

                if existing:
                    for key, value in payload.items():
                        if value is not None and hasattr(existing, key):
                            setattr(existing, key, value)
                else:
                    session.add(TableBySerenityAIStocksLatestPrice(**payload))
            session.commit()
        return True

    def serenity_aistocks_latest_prices_query(self, items: List[dict]) -> List[dict]:
        normalized_keys: list[tuple[str, str]] = []
        for item in items or []:
            market, code = _normalize_serenity_aistocks_market_code(
                item.get("market"), item.get("code")
            )
            if market and code and (market, code) not in normalized_keys:
                normalized_keys.append((market, code))

        if not normalized_keys:
            return []

        with self.Session() as session:
            rows = (
                session.query(TableBySerenityAIStocksLatestPrice)
                .filter(
                    tuple_(
                        TableBySerenityAIStocksLatestPrice.market,
                        TableBySerenityAIStocksLatestPrice.code,
                    ).in_(normalized_keys)
                )
                .all()
            )

            return [
                {
                    "market": row.market,
                    "code": row.code,
                    "symbol": row.symbol or row.code,
                    "price": row.price,
                    "rate": row.rate,
                    "price_text": row.price_text or "--",
                    "rate_text": row.rate_text or "--",
                    "status": row.status or "ok",
                    "source": row.source or "",
                    "fetched_at": row.fetched_at,
                    "updated_at": row.updated_at,
                    "updated_at_text": fun.datetime_to_str(row.updated_at)
                    if row.updated_at is not None
                    else "",
                }
                for row in rows
            ]

    def serenity_aistocks_recent_three_buy_replace(self, rows: List[dict]) -> bool:
        with self.Session() as session:
            now = datetime.datetime.now()
            for row in rows or []:
                market, code = _normalize_serenity_aistocks_market_code(
                    row.get("market"), row.get("code")
                )
                if not market or not code:
                    continue

                existing = (
                    session.query(TableBySerenityAIStocksRecentThreeBuy)
                    .filter(
                        TableBySerenityAIStocksRecentThreeBuy.market == market,
                        TableBySerenityAIStocksRecentThreeBuy.code == code,
                    )
                    .first()
                )

                payload = {
                    "market": market,
                    "code": code,
                    "symbol": row.get("symbol"),
                    "recent_three_buy_time": row.get("recent_three_buy_time"),
                    "recent_three_buy_time_text": row.get("recent_three_buy_time_text"),
                    "label": row.get("label"),
                    "status": row.get("status", "ok"),
                    "source": row.get("source"),
                    "scanned_at": row.get("scanned_at"),
                    "updated_at": row.get("updated_at") or now,
                }

                if existing:
                    for key, value in payload.items():
                        if value is not None and hasattr(existing, key):
                            setattr(existing, key, value)
                else:
                    session.add(TableBySerenityAIStocksRecentThreeBuy(**payload))
            session.commit()
        return True

    def serenity_aistocks_recent_three_buy_query(self, items: List[dict]) -> List[dict]:
        normalized_keys: list[tuple[str, str]] = []
        for item in items or []:
            market, code = _normalize_serenity_aistocks_market_code(
                item.get("market"), item.get("code")
            )
            if market and code and (market, code) not in normalized_keys:
                normalized_keys.append((market, code))

        if not normalized_keys:
            return []

        with self.Session() as session:
            rows = (
                session.query(TableBySerenityAIStocksRecentThreeBuy)
                .filter(
                    tuple_(
                        TableBySerenityAIStocksRecentThreeBuy.market,
                        TableBySerenityAIStocksRecentThreeBuy.code,
                    ).in_(normalized_keys)
                )
                .all()
            )

            return [
                {
                    "market": row.market,
                    "code": row.code,
                    "symbol": row.symbol or row.code,
                    "recent_three_buy_time": row.recent_three_buy_time,
                    "recent_three_buy_time_text": row.recent_three_buy_time_text or "--",
                    "label": row.label or "未扫描",
                    "status": row.status or "ok",
                    "source": row.source or "",
                    "scanned_at": row.scanned_at,
                    "updated_at": row.updated_at,
                    "updated_at_text": fun.datetime_to_str(row.updated_at)
                    if row.updated_at is not None
                    else "",
                }
                for row in rows
            ]

    def news_insert(self, news_data: dict) -> bool:
        """
        插入新闻数据
        :param news_data: 新闻数据字典
        :return: 是否成功
        """
        with self.Session() as session:
            # 检查是否已存在相同的新闻（根据news_id或title+source+published_at）
            existing_news = None
            if news_data.get('story_id'):
                existing_news = session.query(TableByNews).filter(
                    TableByNews.story_id == news_data['story_id']
                ).first()
            
            if not existing_news and news_data.get('title') and news_data.get('source'):
                existing_news = session.query(TableByNews).filter(
                    TableByNews.title == news_data['title'],
                    TableByNews.source == news_data['source'],
                    TableByNews.published_at == news_data.get('published_at')
                ).first()
            
            if existing_news:
                # 更新现有新闻
                for key, value in news_data.items():
                    if hasattr(existing_news, key) and value is not None:
                        setattr(existing_news, key, value)
                existing_news.updated_at = datetime.datetime.now()
            else:
                # 创建新的新闻记录
                print('news_data.get',news_data.get('published_at'))
                news_record = TableByNews(
                    news_id=news_data.get('news_id'),
                    story_id=news_data.get('story_id'),
                    title=news_data.get('title'),
                    body=news_data.get('body'),
                    source=news_data.get('source'),
                    published_at=news_data.get('published_at'),
                    language=news_data.get('language', 'zh'),
                    category=news_data.get('category'),
                    tags=news_data.get('tags'),
                    sentiment_score=news_data.get('sentiment_score'),
                    importance_score=news_data.get('importance_score')
                )
                session.add(news_record)
            
            session.commit()
        return True

    def news_query(self, limit: int = 100, offset: int = 0, 
                   start_date: datetime.datetime = None, 
                   end_date: datetime.datetime = None,
                   source: str = None, category: str = None) -> List[TableByNews]:
        """
        查询新闻数据
        :param limit: 限制返回数量
        :param offset: 偏移量
        :param start_date: 开始日期
        :param end_date: 结束日期
        :param source: 新闻来源
        :param category: 新闻分类
        :return: 新闻列表
        """
        with self.Session() as session:
            query = session.query(TableByNews)
            
            if start_date:
                query = query.filter(TableByNews.published_at >= start_date)
            if end_date:
                query = query.filter(TableByNews.published_at <= end_date)
            if source:
                query = query.filter(TableByNews.source == source)
            if category:
                query = query.filter(TableByNews.category == category)
            
            return query.order_by(TableByNews.published_at.desc()).offset(offset).limit(limit).all()

    def news_search(
        self,
        query_text: str = None,
        keywords: List[str] = None,
        limit: int = 100,
        start_date: datetime.datetime = None,
        end_date: datetime.datetime = None,
        source: str = None,
        category: str = None,
    ) -> List[TableByNews]:
        """
        按关键词搜索新闻
        :param query_text: 主查询词
        :param keywords: 关键词列表
        :param limit: 返回数量
        :param start_date: 开始日期
        :param end_date: 结束日期
        :param source: 新闻来源
        :param category: 新闻分类
        :return: 新闻列表
        """
        with self.Session() as session:
            query = session.query(TableByNews)

            if start_date:
                query = query.filter(TableByNews.published_at >= start_date)
            if end_date:
                query = query.filter(TableByNews.published_at <= end_date)
            if source:
                query = query.filter(TableByNews.source == source)
            if category:
                query = query.filter(TableByNews.category == category)

            search_terms = []
            if query_text:
                cleaned_query = query_text.strip()
                if cleaned_query:
                    search_terms.append(cleaned_query)
            if keywords:
                for keyword in keywords:
                    cleaned_keyword = str(keyword).strip()
                    if cleaned_keyword:
                        search_terms.append(cleaned_keyword)

            if search_terms:
                search_terms = list(dict.fromkeys(search_terms))
                keyword_filters = []
                for term in search_terms:
                    like_term = f"%{term}%"
                    keyword_filters.append(
                        or_(
                            TableByNews.title.like(like_term),
                            TableByNews.body.like(like_term),
                            TableByNews.source.like(like_term),
                            TableByNews.tags.like(like_term),
                        )
                    )
                query = query.filter(or_(*keyword_filters))

            return query.order_by(
                TableByNews.importance_score.desc().nullslast(),
                TableByNews.published_at.desc(),
            ).limit(limit).all()

    def news_get_by_id(self, news_id: str) -> TableByNews:
        """
        根据新闻ID获取新闻
        :param news_id: 新闻ID
        :return: 新闻记录
        """
        with self.Session() as session:
            return session.query(TableByNews).filter(TableByNews.news_id == news_id).first()

    def news_asset_links_replace(self, news_id: str, asset_links: List[dict]) -> bool:
        """
        替换新闻的资产关联关系
        """
        if self.__news_asset_table_ready is False:
            return False
        if not news_id:
            return False

        try:
            with self.Session() as session:
                session.query(TableByNewsAssetLink).filter(
                    TableByNewsAssetLink.news_id == news_id
                ).delete()

                for link in asset_links:
                    session.add(
                        TableByNewsAssetLink(
                            news_id=news_id,
                            asset_code=link.get("asset_code") or link.get("canonical_asset"),
                            canonical_asset=link.get("canonical_asset") or link.get("asset_code"),
                            relation_type=link.get("relation_type", "direct"),
                            confidence=float(link.get("confidence", 0.5)),
                            reason=link.get("reason"),
                            matched_terms=",".join(link.get("matched_terms", []) or []),
                        )
                    )
                session.commit()
        except OperationalError:
            self.__news_asset_table_ready = False
            return False
        return True

    def news_asset_links_query(
        self,
        canonical_asset: str = None,
        relation_type: str = None,
        news_ids: List[str] = None,
        limit: int = 500,
    ) -> List[TableByNewsAssetLink]:
        """
        查询新闻资产关联关系
        """
        if self.__news_asset_table_ready is False:
            return []

        try:
            with self.Session() as session:
                query = session.query(TableByNewsAssetLink)

                if canonical_asset:
                    query = query.filter(TableByNewsAssetLink.canonical_asset == canonical_asset)
                if relation_type:
                    query = query.filter(TableByNewsAssetLink.relation_type == relation_type)
                if news_ids:
                    query = query.filter(TableByNewsAssetLink.news_id.in_(news_ids))

                return query.order_by(
                    TableByNewsAssetLink.confidence.desc(),
                    TableByNewsAssetLink.updated_at.desc(),
                ).limit(limit).all()
        except OperationalError:
            self.__news_asset_table_ready = False
            return []

    def news_delete(self, news_id: str) -> bool:
        """
        删除新闻
        :param news_id: 新闻ID
        :return: 是否成功
        """
        with self.Session() as session:
            session.query(TableByNews).filter(TableByNews.news_id == news_id).delete()
            session.commit()
        return True

    def news_count(self, start_date: datetime.datetime = None, 
                   end_date: datetime.datetime = None,
                   source: str = None, category: str = None) -> int:
        """
        统计新闻数量
        :param start_date: 开始日期
        :param end_date: 结束日期
        :param source: 新闻来源
        :param category: 新闻分类
        :return: 新闻数量
        """
        with self.Session() as session:
            query = session.query(TableByNews)
            
            if start_date:
                query = query.filter(TableByNews.published_at >= start_date)
            if end_date:
                query = query.filter(TableByNews.published_at <= end_date)
            if source:
                query = query.filter(TableByNews.source == source)
            if category:
                query = query.filter(TableByNews.category == category)
            
            return query.count()

    def market_summary_insert(self, summary_data: dict) -> bool:
        """
        保存市场总结数据
        :param summary_data: 总结数据字典
        :return: 是否成功
        """
        with self.Session() as session:
            summary_record = TableByMarketSummary(
                title=summary_data.get('title', '市场总结'),
                content=summary_data.get('content'),
                market=summary_data.get('market'),
                code=summary_data.get('code'),
                summary_type=summary_data.get('summary_type', 'market_analysis'),
                chart_snapshot=summary_data.get('chart_snapshot'),
            )
            session.add(summary_record)
            session.commit()
            return summary_record.id

    def market_summary_query(self, limit: int = 100, offset: int = 0,
                           market: str = None, code: str = None,
                           summary_type: str = None,
                           start_date: datetime.datetime = None,
                           end_date: datetime.datetime = None) -> List[TableByMarketSummary]:
        """
        查询市场总结数据
        :param limit: 限制返回数量
        :param offset: 偏移量
        :param market: 市场
        :param code: 标的代码
        :param summary_type: 总结类型
        :param start_date: 开始日期
        :param end_date: 结束日期
        :return: 总结列表
        """
        with self.Session() as session:
            query = session.query(TableByMarketSummary)
            
            if market:
                query = query.filter(TableByMarketSummary.market == market)
            if code:
                query = query.filter(TableByMarketSummary.code == code)
            if summary_type:
                query = query.filter(TableByMarketSummary.summary_type == summary_type)
            if start_date:
                query = query.filter(TableByMarketSummary.created_at >= start_date)
            if end_date:
                query = query.filter(TableByMarketSummary.created_at <= end_date)
            
            return query.order_by(TableByMarketSummary.created_at.desc()).offset(offset).limit(limit).all()

    def market_summary_get_by_id(self, summary_id: int) -> TableByMarketSummary:
        """
        根据ID获取市场总结
        :param summary_id: 总结ID
        :return: 总结记录
        """
        with self.Session() as session:
            return session.query(TableByMarketSummary).filter(TableByMarketSummary.id == summary_id).first()

    def market_summary_delete(self, summary_id: int) -> bool:
        """
        删除市场总结
        :param summary_id: 总结ID
        :return: 是否成功
        """
        with self.Session() as session:
            session.query(TableByMarketSummary).filter(TableByMarketSummary.id == summary_id).delete()
            session.commit()
        return True

    def market_summary_count(self, market: str = None, code: str = None,
                           summary_type: str = None,
                           start_date: datetime.datetime = None,
                           end_date: datetime.datetime = None) -> int:
        """
        统计市场总结数量
        :param market: 市场
        :param code: 标的代码
        :param summary_type: 总结类型
        :param start_date: 开始日期
        :param end_date: 结束日期
        :return: 总结数量
        """
        with self.Session() as session:
            query = session.query(TableByMarketSummary)
            
            if market:
                query = query.filter(TableByMarketSummary.market == market)
            if code:
                query = query.filter(TableByMarketSummary.code == code)
            if summary_type:
                query = query.filter(TableByMarketSummary.summary_type == summary_type)
            if start_date:
                query = query.filter(TableByMarketSummary.created_at >= start_date)
            if end_date:
                query = query.filter(TableByMarketSummary.created_at <= end_date)
            
            return query.count()

    def economic_data_insert(self, economic_data: dict) -> bool:
        """
        插入经济数据
        :param economic_data: 经济数据字典
        :return: 是否成功
        """
        with self.Session() as session:
            # 检查是否已存在相同的经济数据（根据ds_mnemonic）
            existing_data = None
            if economic_data.get('ds_mnemonic'):
                existing_data = session.query(TableByEconomicData).filter(
                    TableByEconomicData.ds_mnemonic == economic_data['ds_mnemonic']
                ).first()
            print('economic_data',economic_data)
            print('economic_data.get',economic_data.get('latest_value'))
            if existing_data:
                # 更新现有数据
                for key, value in economic_data.items():
                    if hasattr(existing_data, key) and value is not None:
                        setattr(existing_data, key, value)
                existing_data.updated_at = datetime.datetime.now()
            else:
                # 创建新的经济数据记录
                economic_record = TableByEconomicData(
                    indicator_name=economic_data.get('indicator_name'),
                    ds_mnemonic=economic_data.get('ds_mnemonic'),
                    latest_value=economic_data.get('latest_value'),
                    latest_value_date=economic_data.get('latest_value_date'),
                    yoy_change_pct=economic_data.get('yoy_change_pct'),
                    previous_value=economic_data.get('previous_value'),
                    previous_value_date=economic_data.get('previous_value_date'),
                    previous_year_value=economic_data.get('previous_year_value'),
                    year=economic_data.get('year'),
                    units=economic_data.get('units'),
                    source=economic_data.get('source')
                )
                session.add(economic_record)
            
            session.commit()
        return True

    def economic_data_query(self, limit: int = 100, offset: int = 0,
                           year: int = None,
                           ds_mnemonic: str = None,
                           indicator_name: str = None) -> List[TableByEconomicData]:
        """
        查询经济数据
        :param limit: 限制返回数量
        :param offset: 偏移量
        :param year: 年份
        :param ds_mnemonic: 数据源助记符
        :param indicator_name: 指标名称
        :return: 经济数据列表
        """
        with self.Session() as session:
            query = session.query(TableByEconomicData)
            
            if year:
                query = query.filter(TableByEconomicData.year == year)
            if ds_mnemonic:
                query = query.filter(TableByEconomicData.ds_mnemonic == ds_mnemonic)
            if indicator_name:
                query = query.filter(TableByEconomicData.indicator_name.like(f'%{indicator_name}%'))
            
            return query.order_by(TableByEconomicData.id.desc()).offset(offset).limit(limit).all()

    def economic_data_get_by_mnemonic(self, ds_mnemonic: str) -> TableByEconomicData:
        """
        根据数据源助记符获取经济数据
        :param ds_mnemonic: 数据源助记符
        :return: 经济数据记录
        """
        with self.Session() as session:
            return session.query(TableByEconomicData).filter(TableByEconomicData.ds_mnemonic == ds_mnemonic).first()

    def economic_data_delete(self, ds_mnemonic: str) -> bool:
        """
        删除经济数据
        :param ds_mnemonic: 数据源助记符
        :return: 是否成功
        """
        with self.Session() as session:
            session.query(TableByEconomicData).filter(TableByEconomicData.ds_mnemonic == ds_mnemonic).delete()
            session.commit()
        return True

    def economic_data_count(self, year: int = None,
                           ds_mnemonic: str = None,
                           indicator_name: str = None) -> int:
        """
        统计经济数据数量
        :param year: 年份
        :param ds_mnemonic: 数据源助记符
        :param indicator_name: 指标名称
        :return: 经济数据数量
        """
        with self.Session() as session:
            query = session.query(TableByEconomicData)
            
            if year:
                query = query.filter(TableByEconomicData.year == year)
            if ds_mnemonic:
                query = query.filter(TableByEconomicData.ds_mnemonic == ds_mnemonic)
            if indicator_name:
                query = query.filter(TableByEconomicData.indicator_name.like(f'%{indicator_name}%'))
            
            return query.count()

    def market_event_fact_upsert(self, event_fact: Dict[str, Any]) -> bool:
        payload = dict(event_fact or {})
        event_uid = str(payload.get("event_uid") or "").strip() or _build_uid(
            "event",
            {
                "event_type": payload.get("event_type"),
                "asset_class": payload.get("asset_class"),
                "region": payload.get("region"),
                "symbol": payload.get("symbol"),
                "title": payload.get("title"),
                "source_name": payload.get("source_name"),
                "published_at": _to_datetime_value(payload.get("published_at")),
            },
        )
        payload["event_uid"] = event_uid
        with self.Session() as session:
            record = session.query(TableByMarketEventFact).filter(
                TableByMarketEventFact.event_uid == event_uid
            ).first()
            if record is None:
                record = TableByMarketEventFact(event_uid=event_uid)
                session.add(record)
            record.event_type = str(payload.get("event_type") or "unknown")
            record.asset_class = payload.get("asset_class")
            record.region = payload.get("region")
            record.symbol = payload.get("symbol")
            record.title = str(payload.get("title") or payload.get("event_type") or event_uid)
            record.source_name = str(payload.get("source_name") or "unknown")
            record.importance_score = _to_float_value(payload.get("importance_score"))
            record.actual_value = _to_float_value(payload.get("actual_value"))
            record.forecast_value = _to_float_value(payload.get("forecast_value"))
            record.previous_value = _to_float_value(payload.get("previous_value"))
            record.surprise_value = _to_float_value(payload.get("surprise_value"))
            record.published_at = _to_datetime_value(payload.get("published_at"))
            record.effective_at = _to_datetime_value(payload.get("effective_at"))
            record.payload_json = _to_json_text(payload.get("payload") or payload.get("raw_payload"))
            record.updated_at = datetime.datetime.now()
            session.commit()
        return True

    def market_event_fact_query(
        self,
        asset_class: str = None,
        symbol: str = None,
        event_type: str = None,
        source_name: str = None,
        start_datetime: datetime.datetime = None,
        end_datetime: datetime.datetime = None,
        limit: int = 500,
    ) -> List[TableByMarketEventFact]:
        with self.Session() as session:
            query = session.query(TableByMarketEventFact)
            if asset_class:
                query = query.filter(TableByMarketEventFact.asset_class == asset_class)
            if symbol:
                query = query.filter(TableByMarketEventFact.symbol == symbol)
            if event_type:
                query = query.filter(TableByMarketEventFact.event_type == event_type)
            if source_name:
                query = query.filter(TableByMarketEventFact.source_name == source_name)
            if start_datetime:
                query = query.filter(TableByMarketEventFact.published_at >= start_datetime)
            if end_datetime:
                query = query.filter(TableByMarketEventFact.published_at <= end_datetime)
            return (
                query.order_by(TableByMarketEventFact.published_at.desc(), TableByMarketEventFact.id.desc())
                .limit(limit)
                .all()
            )

    def market_factor_snapshot_upsert(self, snapshot: Dict[str, Any]) -> bool:
        payload = dict(snapshot or {})
        snapshot_uid = str(payload.get("snapshot_uid") or "").strip() or _build_uid(
            "factor",
            {
                "factor_group": payload.get("factor_group"),
                "factor_name": payload.get("factor_name"),
                "asset_class": payload.get("asset_class"),
                "symbol": payload.get("symbol"),
                "tenor": payload.get("tenor"),
                "source_name": payload.get("source_name"),
                "as_of_time": _to_datetime_value(payload.get("as_of_time")),
            },
        )
        payload["snapshot_uid"] = snapshot_uid
        with self.Session() as session:
            record = session.query(TableByMarketFactorSnapshot).filter(
                TableByMarketFactorSnapshot.snapshot_uid == snapshot_uid
            ).first()
            if record is None:
                record = TableByMarketFactorSnapshot(snapshot_uid=snapshot_uid)
                session.add(record)
            record.factor_group = str(payload.get("factor_group") or "unknown")
            record.factor_name = str(payload.get("factor_name") or "unknown")
            record.asset_class = payload.get("asset_class")
            record.symbol = payload.get("symbol")
            record.tenor = payload.get("tenor")
            record.value = _to_float_value(payload.get("value"))
            record.unit = payload.get("unit")
            record.change_1d = _to_float_value(payload.get("change_1d"))
            record.change_5d = _to_float_value(payload.get("change_5d"))
            record.zscore_60d = _to_float_value(payload.get("zscore_60d"))
            record.source_name = str(payload.get("source_name") or "unknown")
            record.as_of_time = _to_datetime_value(payload.get("as_of_time")) or datetime.datetime.now()
            record.metadata_json = _to_json_text(payload.get("metadata") or payload.get("payload"))
            record.updated_at = datetime.datetime.now()
            session.commit()
        return True

    def market_factor_snapshot_query(
        self,
        factor_group: str = None,
        factor_name: str = None,
        asset_class: str = None,
        symbol: str = None,
        source_name: str = None,
        limit: int = 500,
    ) -> List[TableByMarketFactorSnapshot]:
        with self.Session() as session:
            query = session.query(TableByMarketFactorSnapshot)
            if factor_group:
                query = query.filter(TableByMarketFactorSnapshot.factor_group == factor_group)
            if factor_name:
                query = query.filter(TableByMarketFactorSnapshot.factor_name == factor_name)
            if asset_class:
                query = query.filter(TableByMarketFactorSnapshot.asset_class == asset_class)
            if symbol:
                query = query.filter(TableByMarketFactorSnapshot.symbol == symbol)
            if source_name:
                query = query.filter(TableByMarketFactorSnapshot.source_name == source_name)
            return (
                query.order_by(TableByMarketFactorSnapshot.as_of_time.desc(), TableByMarketFactorSnapshot.id.desc())
                .limit(limit)
                .all()
            )

    def market_structure_metric_upsert(self, metric: Dict[str, Any]) -> bool:
        payload = dict(metric or {})
        metric_uid = str(payload.get("metric_uid") or "").strip() or _build_uid(
            "metric",
            {
                "asset_class": payload.get("asset_class"),
                "symbol": payload.get("symbol"),
                "metric_name": payload.get("metric_name"),
                "window": payload.get("window"),
                "source_name": payload.get("source_name"),
                "as_of_time": _to_datetime_value(payload.get("as_of_time")),
            },
        )
        payload["metric_uid"] = metric_uid
        with self.Session() as session:
            record = session.query(TableByMarketStructureMetric).filter(
                TableByMarketStructureMetric.metric_uid == metric_uid
            ).first()
            if record is None:
                record = TableByMarketStructureMetric(metric_uid=metric_uid)
                session.add(record)
            record.asset_class = payload.get("asset_class")
            record.symbol = payload.get("symbol")
            record.metric_name = str(payload.get("metric_name") or "unknown")
            record.metric_value = _to_float_value(payload.get("metric_value"))
            record.window = payload.get("window")
            record.cross_section_rank = _to_float_value(payload.get("cross_section_rank"))
            record.source_name = str(payload.get("source_name") or "unknown")
            record.as_of_time = _to_datetime_value(payload.get("as_of_time")) or datetime.datetime.now()
            record.metadata_json = _to_json_text(payload.get("metadata") or payload.get("payload"))
            record.updated_at = datetime.datetime.now()
            session.commit()
        return True

    def market_structure_metric_query(
        self,
        asset_class: str = None,
        symbol: str = None,
        metric_name: str = None,
        source_name: str = None,
        limit: int = 500,
    ) -> List[TableByMarketStructureMetric]:
        with self.Session() as session:
            query = session.query(TableByMarketStructureMetric)
            if asset_class:
                query = query.filter(TableByMarketStructureMetric.asset_class == asset_class)
            if symbol:
                query = query.filter(TableByMarketStructureMetric.symbol == symbol)
            if metric_name:
                query = query.filter(TableByMarketStructureMetric.metric_name == metric_name)
            if source_name:
                query = query.filter(TableByMarketStructureMetric.source_name == source_name)
            return (
                query.order_by(TableByMarketStructureMetric.as_of_time.desc(), TableByMarketStructureMetric.id.desc())
                .limit(limit)
                .all()
            )

    def agent_inference_log_insert(self, log_data: Dict[str, Any]) -> bool:
        payload = dict(log_data or {})
        with self.Session() as session:
            record = TableByAgentInferenceLog(
                run_id=str(payload.get("run_id") or "unknown"),
                agent_name=str(payload.get("agent_name") or "unknown"),
                asset_class=payload.get("asset_class"),
                symbol=payload.get("symbol"),
                question=payload.get("question"),
                thesis=payload.get("thesis"),
                confidence_before=_to_float_value(payload.get("confidence_before")),
                confidence_after=_to_float_value(payload.get("confidence_after")),
                used_event_ids=_to_json_text(payload.get("used_event_ids")),
                used_factor_ids=_to_json_text(payload.get("used_factor_ids")),
                changed_conclusion=str(payload.get("changed_conclusion") or ""),
                metadata_json=_to_json_text(payload.get("metadata") or payload.get("payload")),
                created_at=_to_datetime_value(payload.get("created_at")) or datetime.datetime.now(),
            )
            session.add(record)
            session.commit()
        return True

    def agent_inference_log_query(
        self,
        run_id: str = None,
        agent_name: str = None,
        symbol: str = None,
        limit: int = 500,
    ) -> List[TableByAgentInferenceLog]:
        with self.Session() as session:
            query = session.query(TableByAgentInferenceLog)
            if run_id:
                query = query.filter(TableByAgentInferenceLog.run_id == run_id)
            if agent_name:
                query = query.filter(TableByAgentInferenceLog.agent_name == agent_name)
            if symbol:
                query = query.filter(TableByAgentInferenceLog.symbol == symbol)
            return query.order_by(TableByAgentInferenceLog.created_at.desc(), TableByAgentInferenceLog.id.desc()).limit(limit).all()

    def event_price_reaction_upsert(self, reaction: Dict[str, Any]) -> bool:
        payload = dict(reaction or {})
        reaction_uid = str(payload.get("reaction_uid") or "").strip() or _build_uid(
            "reaction",
            {
                "event_uid": payload.get("event_uid"),
                "symbol": payload.get("symbol"),
                "frequency": payload.get("frequency"),
                "validated_at": _to_datetime_value(payload.get("validated_at")),
            },
        )
        payload["reaction_uid"] = reaction_uid
        with self.Session() as session:
            record = session.query(TableByEventPriceReaction).filter(
                TableByEventPriceReaction.reaction_uid == reaction_uid
            ).first()
            if record is None:
                record = TableByEventPriceReaction(reaction_uid=reaction_uid)
                session.add(record)
            record.event_uid = str(payload.get("event_uid") or "")
            record.symbol = str(payload.get("symbol") or "")
            record.frequency = str(payload.get("frequency") or "30m")
            record.return_30m_pct = _to_float_value(payload.get("return_30m_pct"))
            record.return_120m_pct = _to_float_value(payload.get("return_120m_pct"))
            record.return_1d_pct = _to_float_value(payload.get("return_1d_pct"))
            record.return_5d_pct = _to_float_value(payload.get("return_5d_pct"))
            aligned_value = payload.get("direction_aligned")
            if aligned_value is None or aligned_value == "":
                record.direction_aligned = None
            else:
                record.direction_aligned = 1 if bool(aligned_value) else 0
            record.reaction_label = payload.get("reaction_label")
            record.validated_at = _to_datetime_value(payload.get("validated_at")) or datetime.datetime.now()
            record.metadata_json = _to_json_text(payload.get("metadata") or payload.get("payload"))
            record.updated_at = datetime.datetime.now()
            session.commit()
        return True

    def event_price_reaction_query(
        self,
        event_uid: str = None,
        symbol: str = None,
        frequency: str = None,
        limit: int = 500,
    ) -> List[TableByEventPriceReaction]:
        with self.Session() as session:
            query = session.query(TableByEventPriceReaction)
            if event_uid:
                query = query.filter(TableByEventPriceReaction.event_uid == event_uid)
            if symbol:
                query = query.filter(TableByEventPriceReaction.symbol == symbol)
            if frequency:
                query = query.filter(TableByEventPriceReaction.frequency == frequency)
            return query.order_by(TableByEventPriceReaction.validated_at.desc(), TableByEventPriceReaction.id.desc()).limit(limit).all()

    def company_financials_insert(self, code: str, name: str, statement_type: str, report_date: datetime.date, financials: List[dict]) -> bool:
        """
        批量插入公司财务数据
        :param code: 公司代码
        :param name: 公司名称
        :param statement_type: 报表类型
        :param report_date: 报告期
        :param financials: 财务数据列表，每个元素是一个包含 item_name 和 item_value 的字典
        :return: 是否成功
        """
        with self.Session() as session:
            try:
                records = []
                for financial in financials:
                    # 检查是否已存在相同记录
                    print('financial',financial)
                    exists = session.query(TableByCompanyFinancials).filter_by(
                        code=code,
                        report_date=report_date,
                        statement_type=statement_type,
                        item_name=financial['item_name']
                    ).first()

                    if not exists:
                        record = TableByCompanyFinancials(
                            code=code,
                            name=name,
                            report_date=report_date,
                            statement_type=statement_type,
                            item_name=financial['item_name'],
                            item_value=financial['item_value']
                        )
                        records.append(record)
                print('records',records)
                if records:
                    session.bulk_save_objects(records)
                session.commit()
                return True
            except Exception as e:
                session.rollback()
                print(f"Error inserting company financials: {e}")
                return False



    def company_financials_query(self, code: str = None, name: str = None, statement_type: str = None, report_date_start: datetime.date = None, report_date_end: datetime.date = None, limit: int = 1000) -> List[TableByCompanyFinancials]:
        """
        查询公司财务数据
        :param code: 公司代码
        :param name: 公司名称
        :param statement_type: 报表类型
        :param report_date_start: 报告期开始
        :param report_date_end: 报告期结束
        :param limit: 返回数量限制
        :return: 财务数据列表
        """
        with self.Session() as session:
            query = session.query(TableByCompanyFinancials)
            if code:
                query = query.filter(TableByCompanyFinancials.code == code)
            if name:
                query = query.filter(TableByCompanyFinancials.name == name)
            if statement_type:
                query = query.filter(TableByCompanyFinancials.statement_type == statement_type)
            if report_date_start:
                query = query.filter(TableByCompanyFinancials.report_date >= report_date_start)
            if report_date_end:
                query = query.filter(TableByCompanyFinancials.report_date <= report_date_end)
            
            return query.order_by(TableByCompanyFinancials.report_date.desc(), TableByCompanyFinancials.item_name).limit(limit).all()


db: DB = DB()

if __name__ == "__main__":
    db = DB()

    # db.klines_tables("a", "SH.111111")
    # print("Done")

    # # 增加自选股票
    # db.zx_add_group_stock("a", "我的持仓", "SH.000001", "上证指数", "", "red", location="top")
    # db.zx_add_group_stock("a", "我的持仓", "SH.600519", "贵州茅台", "", "green", location="top")

    # # 获取自选股下的股票代码
    # stocks = db.zx_get_group_stocks("a", "我的持仓")
    # for s in stocks:
    #     print(s.stock_code, s.stock_name, s.stock_color, s.position)

    # db.zx_update_stock_color("a", "我的持仓", "SH.600519", "yellow")
    # db.zx_update_stock_name("a", "我的持仓", "SH.600519", "贵州茅台[yyds]")
    # db.zx_stock_sort_top("a", "我的持仓", "SH.000001")
    # db.zx_stock_sort_bottom("a", "我的持仓", "SH.000001")

    # # 获取自选股下的股票代码
    # stocks = db.zx_get_group_stocks("a", "我的持仓")
    # for s in stocks:
    #     print(s.stock_code, s.stock_name, s.stock_color, s.position)

    # group = db.zx_query_group_by_code("a", "SH.000001")
    # print(group)

    # 订单测试
    # db.order_save(
    #     "a", "SH.000001", "上证指数", "buy", 3100.0, 100, "测试订单", datetime.datetime.now()
    # )
    # orders = db.order_query_by_code("a", "SH.000001")
    # for o in orders:
    #     print(
    #         o.market,
    #         o.stock_code,
    #         o.stock_name,
    #         o.order_type,
    #         o.order_price,
    #         o.order_amount,
    #         o.order_memo,
    #         o.dt,
    #     )
    # db.order_clear_by_code("a", "SH.000001")

    # 提醒任务测试
    # db.task_save(
    #     "a",
    #     "测试提醒任务",
    #     "我的持仓",
    #     "5m,30m",
    #     5,
    #     "up,down",
    #     "1buy,1sell",
    #     "1buy,2sell",
    #     "",
    #     "",
    #     "",
    #     1,
    #     1,
    # )
    # db.task_update(
    #     "a",
    #     "测试提醒任务",
    #     "我的持仓",
    #     "5m,15m",
    #     10,
    #     "up,down",
    #     "1buy,1sell",
    #     "1buy,2sell",
    #     "up",
    #     "xd,pz,qs",
    #     "1buy,",
    #     1,
    #     1,
    # )
    # db.task_delete('a', '测试提醒任务')
    # tasks = db.task_query("a")
    # for t in tasks:
    #     print(t.market, t.task_name, t.zx_group, t.frequencys, t.interval_minutes, t.dt)

    # 警报提醒
    # db.alert_record_save(
    #     "a",
    #     "SH.000001",
    #     "上证指数",
    #     "5m",
    #     "触发提醒",
    #     "笔完成",
    #     "TD",
    #     fun.str_to_datetime("2024-12-16 00:12:00"),
    # )

    # records = db.alert_record_query("a")
    # for r in records:
    #     print(
    #         r.market, r.stock_code, r.stock_name, r.frequency, r.alert_msg, r.alert_dt
    #     )

    # record = db.alert_record_query_by_code(
    #     "a", "SH.000001", "5m", fun.str_to_datetime("2024-12-16 00:12:00")
    # )
    # print(record)
    # print(record.alert_msg)

    # 图表标记
    # db.marks_add("a", "SH.000001", "上证", "", 1234567890, "AB", "测试标记", "cire")
    # marks = db.marks_query("a", "SH.000002")
    # for m in marks:
    #     print(
    #         m.market,
    #         m.stock_code,
    #         m.stock_name,
    #         m.mark_label,
    #         m.mark_tooltip,
    #         m.mark_shape,
    #     )

    # 添加图表标记
    db.marks_add_by_price(
        "a",
        "SH.600378",
        "昊华科技",
        "30m",
        fun.str_to_timeint("2025-07-03 14:00:00"),
        "A",
        "测试标记2",
        "green",
        "red",
    )

    # 缓存
    # db.cache_set("test", "12312312312312", int(time.time()) + 5)
    # v = db.cache_get("test")
    # print(v)

    # from chanlun.exchange.exchange_tdx import ExchangeTDX
    # ex = ExchangeTDX()
    # ex_klines = ex.klines("SH.000001", "d")
    # print(ex_klines)

    # db.klines_insert("a", "SH.000001", "d", ex_klines)

    # klines = db.klines_query("a", "SH.000001", "d", end_date=datetime.datetime.now())
    # for k in klines[-10:]:
    #     print(k.code, k.f, k.dt, k.o, k.c, k.v)

    # last_dt = db.query_klines_last_datetime("a", "SH.000002", "d")
    # print(last_dt)

    # db.delete_klines("a", "SH.000001", "d")

    # insp = sqlalchemy.inspect(db.engine)
    # codes = ['SHFE.ao', 'DCE.jm', 'DCE.rr', 'DCE.j', 'DCE.v', 'DCE.fb', 'DCE.l', 'CZCE.PM', 'DCE.bb', 'CFFEX.TF', 'SHFE.ss', 'CZCE.RS', 'SHFE.au', 'CZCE.TC', 'DCE.c', 'SHFE.fu', 'CZCE.PF', 'SHFE.al', 'CFFEX.TS', 'DCE.cs', 'SHFE.wr', 'DCE.y', 'INE.sc', 'CZCE.WH', 'CZCE.WS', 'CZCE.PK', 'CZCE.WT', 'CZCE.OI', 'SHFE.ru', 'DCE.eg', 'SHFE.ag', 'INE.bc', 'SHFE.zn', 'CZCE.RI', 'CZCE.ME', 'SHFE.br', 'CZCE.UR', 'INE.lu', 'CZCE.JR', 'CZCE.RM', 'CZCE.SA', 'DCE.lh', 'INE.nr', 'CZCE.SR', 'CZCE.MA', 'SHFE.hc', 'DCE.b', 'CFFEX.TL', 'CFFEX.IH', 'CZCE.ZC', 'CZCE.PX', 'DCE.jd', 'GFEX.si', 'SHFE.sn', 'CZCE.AP', 'CZCE.ER', 'CZCE.RO', 'CFFEX.IM', 'CZCE.FG', 'SHFE.bu', 'CFFEX.IF', 'INE.ec', 'DCE.m', 'CZCE.LR', 'SHFE.cu', 'DCE.a', 'CZCE.TA', 'DCE.pp', 'CZCE.CY', 'SHFE.ni', 'DCE.i', 'SHFE.sp', 'CZCE.SM', 'DCE.pg', 'CZCE.CJ', 'SHFE.pb', 'CFFEX.T', 'CZCE.SH', 'CZCE.SF', 'CFFEX.IC', 'CZCE.CF', 'DCE.eb', 'GFEX.lc', 'DCE.p', 'SHFE.rb']
    # for table in insp.get_table_names():
    #     if table.startswith("futures_"):
    #         print(f"DROP TABLE `{table}`;")

    # record = db.alert_record_query_by_code(
    #     "a", "SZ.300014", "5m", "bi", fun.str_to_datetime("2023-12-25 13:55:00")
    # )
    # print(record)
    
    # 测试新闻数据操作
    # news_data = {
    #     'news_id': '12345',
    #     'title': '测试新闻标题',
    #     'body': '测试新闻内容',
    #     'source': '测试来源',
    #     'published_at': datetime.datetime.now()
    # }
    # db.news_insert(news_data)
    # news_list = db.news_query(limit=10)
    # print(f"查询到 {len(news_list)} 条新闻")
