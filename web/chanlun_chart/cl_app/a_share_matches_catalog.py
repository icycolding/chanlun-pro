from __future__ import annotations

import datetime as dt
from typing import Any

from chanlun.base import Market
from chanlun.db import db
from chanlun.exchange import get_exchange
import pandas as pd

from .a_share_matches_quotes import build_chart_url
from .a_share_matches_quotes import fetch_tick_snapshots, normalize_a_share_code
from .a_share_stock_analysis import build_stock_analysis_detail_url
from .a_share_matches_tweet_notes import get_project_tweet_note


_THEME_INDEX_REFERENCE_STATE_CACHE: dict[str, tuple[str, dict[str, float]]] = {}


_THEME_ACCENTS: dict[str, dict[str, str]] = {
    "光模块 / CPO / 光子器件": {
        "accent": "#7dd3fc",
        "accent_soft": "rgba(125, 211, 252, 0.12)",
        "accent_line": "rgba(125, 211, 252, 0.28)",
    },
    "光子材料 / 衬底 / 外延 / SOI": {
        "accent": "#a78bfa",
        "accent_soft": "rgba(167, 139, 250, 0.12)",
        "accent_line": "rgba(167, 139, 250, 0.28)",
    },
    "AI互连 / 连接芯片 / AEC": {
        "accent": "#38bdf8",
        "accent_soft": "rgba(56, 189, 248, 0.12)",
        "accent_line": "rgba(56, 189, 248, 0.28)",
    },
    "存储 / SSD / Memory Cycle": {
        "accent": "#fb7185",
        "accent_soft": "rgba(251, 113, 133, 0.12)",
        "accent_line": "rgba(251, 113, 133, 0.28)",
    },
    "Neocloud / 算力租赁 / GPU供给": {
        "accent": "#22d3ee",
        "accent_soft": "rgba(34, 211, 238, 0.12)",
        "accent_line": "rgba(34, 211, 238, 0.28)",
    },
    "晶圆代工 / Specialty Foundry": {
        "accent": "#f59e0b",
        "accent_soft": "rgba(245, 158, 11, 0.12)",
        "accent_line": "rgba(245, 158, 11, 0.28)",
    },
    "先进封装 / HBM / 玻璃基板": {
        "accent": "#f97316",
        "accent_soft": "rgba(249, 115, 22, 0.12)",
        "accent_line": "rgba(249, 115, 22, 0.28)",
    },
    "商业航天": {
        "accent": "#34d399",
        "accent_soft": "rgba(52, 211, 153, 0.12)",
        "accent_line": "rgba(52, 211, 153, 0.28)",
    },
    "电力 / 电网 / Power Bottleneck": {
        "accent": "#fde047",
        "accent_soft": "rgba(253, 224, 71, 0.12)",
        "accent_line": "rgba(253, 224, 71, 0.28)",
    },
    "关键矿物 / 战略材料": {
        "accent": "#c084fc",
        "accent_soft": "rgba(192, 132, 252, 0.12)",
        "accent_line": "rgba(192, 132, 252, 0.28)",
    },
    "机器人 / 具身智能 / 核心部件": {
        "accent": "#2dd4bf",
        "accent_soft": "rgba(45, 212, 191, 0.12)",
        "accent_line": "rgba(45, 212, 191, 0.28)",
    },
    "量子计算 / 精密制造 / 上游设备": {
        "accent": "#60a5fa",
        "accent_soft": "rgba(96, 165, 250, 0.12)",
        "accent_line": "rgba(96, 165, 250, 0.28)",
    },
}


_PROJECT_STOCK_REASON_DATA: dict[str, dict[str, Any]] = {
    "SIVE": {
        "serenity_reason_summary": "Serenity 看 SIVE，不是把它当普通通信股，而是把它放在激光与 CPO 上游 choke point 的位置。核心吸引力在于它更靠近外部光源、laser 与 photonics 链条的上游约束，市场却常常还没把这种上游稀缺性完全 price in。若 CPO 与高密度光互连继续推进，SIVE 的价值更像“卡位资源”而不是单纯景气 beta。",
        "serenity_reason_highlights": ["laser / CPO 上游卡位", "更像 choke point 而非模组受益", "市场定价往往慢于技术路径变化"],
        "tweet_detail_label": "查看推荐脉络",
    },
    "LITE": {
        "serenity_reason_summary": "Serenity 看 LITE，重点通常不是传统光模块叙事，而是它在光器件、CPO 与 photonics 平台能力上的承接。它既能受益于 AI 光互连放量，又有平台型器件公司的属性，因此更适合作为产业平台观察标的。推荐逻辑偏向“谁能稳定承接下一代光互连平台”，而不是短期模组出货。",
        "serenity_reason_highlights": ["光器件平台能力", "CPO 承接者", "AI 光互连平台化受益"],
        "tweet_detail_label": "查看推荐脉络",
    },
    "AAOI": {
        "serenity_reason_summary": "Serenity 对 AAOI 的关注更偏向激光链条、光引擎和 transceiver 的交叉位置，而不只是高速模组行情。它的吸引力在于处在 AI 光互连的关键过渡层，既能看激光器件，又能看模块产品化。真正的推荐理由通常是它可能在技术路径切换时获得重新定价，而不是单纯跟涨。",
        "serenity_reason_highlights": ["激光 + transceiver 双重属性", "AI 光互连过渡层", "可能受益于重新定价"],
        "tweet_detail_label": "查看推荐脉络",
    },
    "COHR": {
        "serenity_reason_summary": "Serenity 看 COHR，核心在激光、光器件和 datacom photonics 的平台地位。它不是最纯的单点瓶颈公司，但在关键器件与光学平台上的积累，使它能承接 AI 光互连主线里的多种需求。推荐理由更多来自它在器件平台与上游能力上的厚度，而不是单一产品景气。",
        "serenity_reason_highlights": ["激光与光器件平台", "datacom photonics 受益", "多产品线承接 AI 光学需求"],
        "tweet_detail_label": "查看推荐脉络",
    },
    "POET": {
        "serenity_reason_summary": "Serenity 看 POET，重点通常放在 external light source、optical engine 和 photonic integration 的新方案价值。它吸引人的地方是技术路径新、市场关注度还没完全扩散，同时又卡在 CPO 与光引擎方案的关键节点。推荐逻辑更像“押注技术路线和平台渗透”，而不是传统成熟器件公司的稳态估值。",
        "serenity_reason_highlights": ["external light source 方案", "optical engine / 光电集成", "新技术路径带来的重估"],
        "tweet_detail_label": "查看推荐脉络",
    },
    "AXTI": {
        "serenity_reason_summary": "Serenity 看 AXTI，明显是按上游材料和 InP / III-V 衬底链来看的。真正吸引力在于它处在化合物半导体和 photonics 的基底层，属于产业要往上做时绕不开的上游材料。推荐理由不是短期主题热度，而是材料 choke point 和供给位置。",
        "serenity_reason_highlights": ["InP / III-V 上游材料", "化合物半导体基底层", "材料 choke point"],
        "tweet_detail_label": "查看推荐脉络",
    },
    "IQE": {
        "serenity_reason_summary": "Serenity 看 IQE，通常是把它放在 epiwafer 和 compound semiconductor upstream 的位置。它的价值在于处在外延片和上游材料层，离最终产品远，却更接近真正难替代的制造前段。推荐理由偏向“上游验证后弹性大、市场理解却滞后”。",
        "serenity_reason_highlights": ["epiwafer / 外延片上游", "compound semiconductor upstream", "市场理解常慢于产业验证"],
        "tweet_detail_label": "查看推荐脉络",
    },
    "SOI": {
        "serenity_reason_summary": "Serenity 看 Soitec，最核心的是它在 SOI 衬底和高端基底上的稀缺地位。它更像基础材料平台而不是终端器件公司，因此推荐逻辑来自 supply chain choke point 和高端基底垄断属性。只要硅光、射频和先进器件继续推进，Soitec 的地位就会不断被验证。",
        "serenity_reason_highlights": ["SOI 衬底稀缺性", "高端基底平台", "硅光与先进器件的底层受益者"],
        "tweet_detail_label": "查看推荐脉络",
    },
    "ALAB": {
        "serenity_reason_summary": "Serenity 看 Astera Labs，核心不是泛 AI 概念，而是它在 CXL、PCIe retimer、switch 和 AI 服务器互连层的协议卡位。它属于真正受益于 AI 系统复杂度提升的连接芯片层，而不是简单拼算力资本开支。推荐理由更偏底层互连标准升级和架构复杂化。",
        "serenity_reason_highlights": ["CXL / PCIe 互连卡位", "AI 服务器连接芯片", "受益于系统架构复杂化"],
        "tweet_detail_label": "查看推荐脉络",
    },
    "CRDO": {
        "serenity_reason_summary": "Serenity 看 Credo，重点在 AEC、铜连接和高速互连链条，而不是泛网络设备叙事。它吸引人的地方是站在 AI 互连升级的基础设施层，直接受益于更高带宽和更复杂布线需求。推荐理由通常来自底层连接标准变化，而不是单纯交换机景气。",
        "serenity_reason_highlights": ["AEC / 铜连接", "高速互连升级", "基础设施层标准变化受益"],
        "tweet_detail_label": "查看推荐脉络",
    },
    "AVGO": {
        "serenity_reason_summary": "Serenity 看 Broadcom，在 AI 互连主题里更重视它对 AI Ethernet 交换芯片与 scale-up fabric 的卡位，而不是把它当泛半导体权重股。真正的吸引力来自交换芯片、网络栈和自定义 AI 加速器一起推升集群扩容，这比单纯的铜缆和连接器更接近真实互连约束。",
        "serenity_reason_highlights": ["AI Ethernet 交换芯片", "scale-up fabric", "更接近真实互连卡点"],
        "tweet_detail_label": "查看推荐脉络",
    },
    "SNDK": {
        "serenity_reason_summary": "Serenity 看 SanDisk，主要是在看 NAND 重定价和 memory cycle，而不是把它当普通消费电子存储股。吸引力在于存储价格拐点一旦确认，经营杠杆和周期弹性会非常直接。推荐逻辑更偏周期错配和库存出清后的重估。",
        "serenity_reason_highlights": ["NAND 重定价", "memory cycle 修复", "库存出清后的周期重估"],
        "tweet_detail_label": "查看推荐脉络",
    },
    "NBIS": {
        "serenity_reason_summary": "Serenity 看 Nebius，更像是在看 neocloud 与 AI 基础设施供给缺口，而不是普通云计算故事。它的关键在于谁能承接真实 GPU 需求、交付算力资源并形成平台能力。推荐理由偏向供给侧稀缺与算力租赁平台化，而不是单纯 IDC 扩产。",
        "serenity_reason_highlights": ["neocloud 供给缺口", "GPU 资源平台化", "供给侧稀缺性"],
        "tweet_detail_label": "查看推荐脉络",
    },
    "TSM": {
        "serenity_reason_summary": "Serenity 看 TSM，是把它视为 AI 半导体最核心的 foundry 锚。它不是一个普通制造股，而是先进逻辑、产能配置、工艺领导力和 AI 资本开支的共同交汇点。推荐理由更多来自“它是整个产业链最关键的产能中枢”。",
        "serenity_reason_highlights": ["AI 半导体 foundry 锚", "先进逻辑产能中枢", "工艺领导力决定产业节奏"],
        "tweet_detail_label": "查看推荐脉络",
    },
    "TSEM": {
        "serenity_reason_summary": "Serenity 看 Tower，更偏特色工艺、模拟、功率和 photonics foundry，而不是先进逻辑。它的价值在于处在一些高附加值但不显眼的制造环节，市场通常不如看 TSM 那样热，但这类特色工艺更容易出现错配。推荐逻辑偏向 niche foundry 的稳定卡位。",
        "serenity_reason_highlights": ["specialty foundry", "模拟 / 功率 / photonics 工艺", "niche 制造卡位"],
        "tweet_detail_label": "查看推荐脉络",
    },
    "XFAB": {
        "serenity_reason_summary": "Serenity 看 X-Fab，主要是在看 silicon photonics 和 specialty foundry 的交叉价值。它不是最热门的名字，但可能处在更细分、更难替代的制造位置。推荐理由来自特色工艺与硅光需求的长期耦合，而不是单纯看晶圆代工景气。",
        "serenity_reason_highlights": ["silicon photonics foundry", "specialty 工艺", "细分制造位置更难替代"],
        "tweet_detail_label": "查看推荐脉络",
    },
    "TOWA": {
        "serenity_reason_summary": "Serenity 看 TOWA，更像在看先进封装和 HBM 设备链，而不是一般半导体设备 beta。关键点在于先进封装工艺正在成为 AI 时代新的瓶颈，封装设备的重要性被明显抬升。推荐理由来自“封装正在接近前道制造的重要性”。",
        "serenity_reason_highlights": ["先进封装 / HBM 设备", "封装成为新瓶颈", "AI 时代后段工艺重要性抬升"],
        "tweet_detail_label": "查看推荐脉络",
    },
    "LPK": {
        "serenity_reason_summary": "Serenity 看 LPK thesis，通常是把它当成玻璃基板和先进封装新材料方向的前瞻下注。吸引力不在现有体量，而在于如果封装路线切到玻璃基板，相关材料和设备链会被整体重估。推荐理由偏向技术路线变化带来的期权价值。",
        "serenity_reason_highlights": ["玻璃基板 thesis", "先进封装新材料", "技术路线切换的期权价值"],
        "tweet_detail_label": "查看推荐脉络",
    },
    "RKLB": {
        "serenity_reason_summary": "Serenity 看 Rocket Lab，重点是它在商业航天里兼具发射、系统和平台延展的能力。它不是纯火箭题材，而更像 SpaceX 之外最值得跟踪的系统级玩家之一。推荐理由来自它可能在商业航天生态中持续抬升的位置，而不是单次发射新闻。",
        "serenity_reason_highlights": ["商业航天系统级玩家", "发射 + 平台能力", "非单次事件驱动"],
        "tweet_detail_label": "查看推荐脉络",
    },
    "-": {
        "serenity_reason_summary": "Serenity 关注 SpaceX，不是因为它是热门私营公司，而是因为它代表了发射、卫星互联网和系统集成的最高标准。它更多是整个商业航天链的锚定参照物，用来反推谁能接近其生态与能力。推荐理由本质上是“定义行业边界的公司”。",
        "serenity_reason_highlights": ["商业航天锚定参照物", "发射 + 星链 + 系统集成", "定义行业边界"],
        "tweet_detail_label": "查看推荐脉络",
    },
    "XLU": {
        "serenity_reason_summary": "Serenity 看 XLU，不是传统公用事业防御逻辑，而是把它放到 AI power bottleneck 里看。随着 AI 数据中心耗电提升，电网投资、输配电升级和公用事业 capex 都可能进入新的周期。推荐理由偏向“电力是 AI 时代的真实瓶颈之一”。",
        "serenity_reason_highlights": ["AI power bottleneck", "电网升级", "公用事业 capex 新周期"],
        "tweet_detail_label": "查看推荐脉络",
    },
    "VNP": {
        "serenity_reason_summary": "Serenity 看 5N Plus，核心是关键矿物、战略材料与供应链安全，而不是普通有色资源故事。它的吸引力来自材料自主可控、关键元素供给和高端工业链需求的重合。推荐理由更偏向战略地位与上游资源卡位。",
        "serenity_reason_highlights": ["关键矿物 / 战略材料", "供应链安全", "上游资源卡位"],
        "tweet_detail_label": "查看推荐脉络",
    },
    "VPG": {
        "serenity_reason_summary": "Serenity 看 VPG，不是把它当普通传感器公司，而是把它放到机器人手部、力控和高精度 sensing 的关键位置。真正有价值的不是“机器人概念”本身，而是那些在高自由度、难替代部位里的精密器件。如果具身智能进入高端工业或复杂操作场景，VPG 这种高精度 sensing 更容易成为高附加值 choke point。",
        "serenity_reason_highlights": ["高精度 sensing", "机器人手部 / 力控", "高附加值部位更接近 choke point"],
        "tweet_detail_label": "查看推荐脉络",
    },
    "AEVA": {
        "serenity_reason_summary": "Serenity 看 AEVA，重点不只是自动驾驶，而是 FMCW LiDAR 在 physical AI / robotics 里的感知价值。它的吸引力在于 deterministic velocity 与更高质量的空间理解能力，这更像具身智能感知层的底层升级，而不是单一硬件主题。推荐逻辑偏向“谁能在机器人感知层卡住下一代 sensing 路径”。",
        "serenity_reason_highlights": ["FMCW LiDAR", "具身智能感知", "physical AI 的底层 sensing 路径"],
        "tweet_detail_label": "查看推荐脉络",
    },
    "SSYS": {
        "serenity_reason_summary": "Serenity 看 SSYS，不是按传统 3D 打印周期股来解读，而是把它放进 humanoid frame、轻量结构和美国本土制造认证的路径里。真正有吸引力的是机器人骨架和结构件在放量初期需要被验证过的材料与制造方案，而 SSYS 更像这一层的工具与平台承接者。",
        "serenity_reason_highlights": ["机器人骨架 / 结构件", "3D 打印材料与工艺", "美国本土制造认证路径"],
        "tweet_detail_label": "查看推荐脉络",
    },
    "INFQ": {
        "serenity_reason_summary": "Serenity 看 INFQ，核心不是泛量子概念，而是它已经具备量子 sensing 收入和更接近商业化的量子计算路径。它比只停留在 science project 阶段的量子名字更值得跟踪，因为量子 sensing、政府与军工订单给了它更真实的验证层。推荐逻辑偏向“离设备化和收入更近的量子样本”。",
        "serenity_reason_highlights": ["neutral-atom 量子计算", "量子 sensing 收入", "比 science project 更接近商业化"],
        "tweet_detail_label": "查看推荐脉络",
    },
    "ALRIB": {
        "serenity_reason_summary": "Serenity 看 ALRIB，本质上是在看 MBE 设备和量子器件制造前段的位置。它并不是量子应用层的热闹故事，而是更上游、更冷门但更接近精密制造 choke point 的设备样本。推荐理由来自“如果量子器件工艺真的走向放量，前段精密设备会先被重估”。",
        "serenity_reason_highlights": ["MBE 精密制造设备", "量子器件前段工艺", "更接近设备 choke point"],
        "tweet_detail_label": "查看推荐脉络",
    },
}


def _fit_level(score: int) -> str:
    if score >= 18:
        return "高"
    if score >= 14:
        return "中高"
    if score >= 10:
        return "中"
    return "观察"


def _source(title: str, url: str, source: str) -> dict[str, str]:
    return {
        "title": title,
        "url": url,
        "source": source,
    }


def _source_validation(
    summary: str = "",
    sources: list[dict[str, str]] | None = None,
    status: str = "已认证",
) -> dict[str, Any]:
    normalized_sources = sources or []
    return {
        "status": status if normalized_sources else "未认证",
        "summary": summary if normalized_sources else "",
        "sources": normalized_sources,
    }


def _selection_reason(summary: str = "", fit_basis: str = "") -> dict[str, str]:
    return {
        "summary": str(summary or "仍需补充这只股票为什么符合 Serenity 方法。"),
        "fit_basis": str(fit_basis or "仍需补充它卡住的环节与为什么不是普通受益股。"),
    }


def _scarcity_view(label: str = "待验证", detail: str = "") -> dict[str, str]:
    return {
        "label": str(label or "待验证"),
        "detail": str(detail or "当前来源已说明链条位置，但稀缺性强弱仍需继续核对。"),
    }


def _capacity_view(label: str = "待验证", detail: str = "") -> dict[str, str]:
    return {
        "label": str(label or "待验证"),
        "detail": str(detail or "扩产节奏与客户验证仍需持续跟踪。"),
    }


def _pricing_view(label: str = "待验证", detail: str = "") -> dict[str, str]:
    return {
        "label": str(label or "待验证"),
        "detail": str(detail or "价格传导路径暂未完全确认，需结合供需和客户验证继续判断。"),
    }


def _market_cap_research(current_text: str = "", upside_text: str = "") -> dict[str, str]:
    return {
        "current_text": str(current_text or "研究市值待补充"),
        "upside_text": str(upside_text or "上行情形待补充"),
    }


def _segment_market_view(
    market_size_text: str = "",
    company_share_text: str = "",
    share_level: str = "",
) -> dict[str, str]:
    return {
        "market_size_text": str(market_size_text or "对应环节市场规模待研究补齐"),
        "company_share_text": str(company_share_text or "公司份额待研究补齐"),
        "share_level": str(share_level or "待补充"),
    }


_PROJECT_SOURCE_VALIDATIONS: dict[str, dict[str, Any]] = {
    "SIVE": _source_validation(
        summary="官方光子交换路线与权威媒体均支持外置光源和上游激光仍是 CPO 关键卡点。",
        sources=[
            _source("NVIDIA Spectrum-X Photonics 官方新闻稿", "https://investor.nvidia.com/news/press-release-details/2025/NVIDIA-Announces-Spectrum-X-Photonics-Co-Packaged-Optics-Networking-Switches-to-Scale-AI-Factories-to-Millions-of-GPUs/default.aspx", "官方新闻稿"),
            _source("EE Times: AI demand reshapes optical roadmaps", "https://www.eetimes.com/ai-demand-reshapes-optical-connectivity-and-photonics-roadmaps/", "权威媒体"),
        ],
    ),
    "LITE": _source_validation(
        summary="NVIDIA 与 Broadcom 官方材料都表明器件平台与光引擎在中期价值链里更重要。",
        sources=[
            _source("NVIDIA Silicon Photonics 官方产品页", "https://www.nvidia.com/en-gb/networking/products/silicon-photonics/", "官网产品页"),
            _source("Broadcom Tomahawk 6 Davisson 新闻稿", "https://www.broadcom.com/company/news/product-releases/63626", "官方新闻稿"),
        ],
    ),
    "AAOI": _source_validation(
        summary="NVIDIA 生态认证和权威行业媒体共同验证了光模块与器件平台仍是现金流中心。",
        sources=[
            _source("NVIDIA Spectrum-X Photonics 官方新闻稿", "https://investor.nvidia.com/news/press-release-details/2025/NVIDIA-Announces-Spectrum-X-Photonics-Co-Packaged-Optics-Networking-Switches-to-Scale-AI-Factories-to-Millions-of-GPUs/default.aspx", "官方新闻稿"),
            _source("EE Times: AI demand reshapes optical roadmaps", "https://www.eetimes.com/ai-demand-reshapes-optical-connectivity-and-photonics-roadmaps/", "权威媒体"),
        ],
    ),
    "COHR": _source_validation(
        summary="NVIDIA 官方生态名单与 Broadcom 的 CPO 路线材料都支持器件平台价值继续上移。",
        sources=[
            _source("NVIDIA Silicon Photonics 官方产品页", "https://www.nvidia.com/en-gb/networking/products/silicon-photonics/", "官网产品页"),
            _source("Broadcom Tomahawk 6 Davisson 新闻稿", "https://www.broadcom.com/company/news/product-releases/63626", "官方新闻稿"),
        ],
    ),
    "POET": _source_validation(
        summary="NVIDIA 官方路线与行业媒体都验证 optical engine / external light source 仍处于前瞻验证期。",
        sources=[
            _source("NVIDIA Spectrum-X Photonics 官方新闻稿", "https://investor.nvidia.com/news/press-release-details/2025/NVIDIA-Announces-Spectrum-X-Photonics-Co-Packaged-Optics-Networking-Switches-to-Scale-AI-Factories-to-Millions-of-GPUs/default.aspx", "官方新闻稿"),
            _source("EE Times: AI demand reshapes optical roadmaps", "https://www.eetimes.com/ai-demand-reshapes-optical-connectivity-and-photonics-roadmaps/", "权威媒体"),
        ],
    ),
    "AXTI": _source_validation(
        summary="公司材料与业绩公告都验证了 InP 衬底被 AI 数据中心需求重新拉动。",
        sources=[
            _source("AXT Investor Overview", "https://investors.axt.com/Investors/Overview/", "公司官网"),
            _source("AXT FY2025 Results", "https://investors.axt.com/Investors/news/news-details/2026/AXT-Inc--Announces-Fourth-Quarter-and-Fiscal-Year-2025-Financial-Results/default.aspx", "公司业绩公告"),
        ],
    ),
    "IQE": _source_validation(
        summary="官方多年协议验证了 InP epiwafer 已进入 AI 数据中心真实供应链。",
        sources=[
            _source("Tower/IQE InP epiwafer agreement", "https://ir.towersemi.com/news-releases/news-release-details/iqe-and-tower-semiconductor-announce-multi-year-inp-epiwafer", "官方新闻稿"),
            _source("AXT FY2025 Results", "https://investors.axt.com/Investors/news/news-details/2026/AXT-Inc--Announces-Fourth-Quarter-and-Fiscal-Year-2025-Financial-Results/default.aspx", "行业对照"),
        ],
    ),
    "SOI": _source_validation(
        summary="Soitec 业绩与中国授权延长共同验证 Photonics-SOI 已成为 AI 数据中心核心基底之一。",
        sources=[
            _source("Soitec FY26 Results", "https://www.soitec.com/home/group/newsroom/press-releases/content/2026/05/27/soitec-reports-fiscal-2026-full-year-results", "公司业绩公告"),
            _source("Soitec 与 NSIG 授权延长", "https://www.soitec.com/home/group/newsroom/press-releases/content/2026/03/13/soitec-and-nsig-to-agree-extension-of-licensing-framework", "官方新闻稿"),
        ],
    ),
    "ALAB": _source_validation(
        summary="官方量产爬坡与产品部署说明都验证了其 PCIe/CXL Retimer 的真实卡位。",
        sources=[
            _source("Astera PCIe 6 ramp", "https://www.asteralabs.com/news/astera-labs-ramps-production-of-pcie-6-connectivity-portfolio-supercharging-advanced-ai-and-cloud-infrastructure-deployments/", "官方新闻稿"),
            _source("Aries Retimers 产品页", "https://www.asteralabs.com/products/aries/pcie-cxl-smart-dsp-retimers/", "官网产品页"),
        ],
    ),
    "CRDO": _source_validation(
        summary="财报与电话会共同验证 AEC 已从展示走向 hyperscaler 收入兑现。",
        sources=[
            _source("Credo FY2025 Results", "https://www.nasdaq.com/press-release/credo-technology-group-holding-ltd-reports-fourth-quarter-and-fiscal-year-2025", "财报新闻稿"),
            _source("Credo Q4 FY2025 Transcript", "https://www.barchart.com/story/news/32686625/credo-tech-crdo-q4-2025-earnings-call-transcript", "业绩会纪要"),
        ],
    ),
    "AVGO": _source_validation(
        summary="Broadcom 财报与产品发布同时验证其 AI Ethernet switch 已成为 AI 集群扩容硬约束。",
        sources=[
            _source("Broadcom FY2025 Results", "https://www.broadcom.com/company/news/financial-releases/63716", "财报公告"),
            _source("Tomahawk Ultra 发布", "https://www.broadcom.com/company/news/product-releases/63341", "官方新闻稿"),
        ],
    ),
    "SNDK": _source_validation(
        summary="Sandisk 官方年报与 FY2025 业绩公告共同验证其已独立运营，并继续围绕 NAND 与 AI 相关存储机会布局。",
        sources=[
            _source("Sandisk Annual Reports", "https://investor.sandisk.com/financial-information/annual-reports", "公司年报"),
            _source("Sandisk FY2025 Q4 Results", "https://www.sandisk.com/company/newsroom/press-releases/2025/2025-08-14-sandisk-reports-fiscal-fourth-quarter-2025-financial-results", "业绩公告"),
        ],
    ),
    "NBIS": _source_validation(
        summary="Nebius 财报与 SEC 年报共同验证其 AI cloud 收入增长和宾州 AI factory 的电力资源储备。",
        sources=[
            _source("Nebius Q1 2026 Results", "https://www.nasdaq.com/press-release/nebius-reports-first-quarter-2026-financial-results-2026-05-13", "业绩公告"),
            _source("Nebius 20-F/A", "https://www.sec.gov/Archives/edgar/data/1513845/000110465926065681/nbis-20251231x20fa.htm", "SEC年报"),
        ],
    ),
    "TSM": _source_validation(
        summary="TSMC 官方年报与董事会 6-K 同时验证其 2025 年经营表现和持续高强度资本开支。",
        sources=[
            _source("TSMC Annual Reports", "https://investor.tsmc.com/english/annual-reports", "公司年报"),
            _source("TSMC Board Resolution 6-K", "https://www.sec.gov/Archives/edgar/data/1046179/000104617926000017/tsm-boardx20260210x6k.htm", "SEC公告"),
        ],
    ),
    "TOWA": _source_validation(
        summary="TOWA 官方 IR 与综合报告共同验证其半导体封装设备平台定位。",
        sources=[
            _source("TOWA IR Library", "https://www.towajapan.co.jp/en/ir/library/", "公司IR"),
            _source("TOWA Integrated Report", "https://www.towajapan.co.jp/en/ir/corporatereport/", "综合报告"),
        ],
    ),
    "RKLB": _source_validation(
        summary="Rocket Lab 财报与 10-K 共同验证其发射频次、订单与系统平台能力持续提升。",
        sources=[
            _source("Rocket Lab FY2025 Results", "https://investors.rocketlabcorp.com/news-releases/news-release-details/rocket-lab-announces-fourth-quarter-and-full-year-2025-financial", "业绩公告"),
            _source("Rocket Lab 2025 Form 10-K", "https://investors.rocketlabcorp.com/node/12096/html", "SEC年报"),
        ],
    ),
    "XLU": _source_validation(
        summary="SSGA 官方基金页与 SEC 说明书共同验证 XLU 作为公用事业板块 ETF 的资产配置与跟踪目标。",
        sources=[
            _source("XLU Fund Page", "https://www.ssga.com/us/en/intermediary/etfs/funds/the-utilities-select-sector-spdr-fund-xlu?fundSeoName=utilities-select-sector-spdr-fund-XLU", "基金官网"),
            _source("XLU Summary Prospectus", "https://www.sec.gov/Archives/edgar/data/1064641/000119312526031732/d96415d497k.htm", "SEC说明书"),
        ],
    ),
    "VNP": _source_validation(
        summary="5N Plus 财务文件与季度业绩公告共同验证其高性能材料与关键矿物链条的经营进展。",
        sources=[
            _source("5N Plus Financial Documents", "https://www.5nplus.com/en/investors/financial-documents/", "公司财务文件"),
            _source("5N Plus Q1 2026 Results", "https://www.5nplus.com/en/news/5n-plus-inc-reports-first-quarter-2026-financials/", "业绩公告"),
        ],
    ),
    "VPG": _source_validation(
        summary="VPG 官方年报与 10-K 共同验证其精密测量与高精度传感业务结构。",
        sources=[
            _source("VPG Annual Reports", "https://ir.vpgsensors.com/financials/annual-reports/default.aspx", "公司年报"),
            _source("VPG 2024 Form 10-K", "https://www.sec.gov/Archives/edgar/data/1487952/000148795225000014/vpg-20241231.htm", "SEC年报"),
        ],
    ),
    "INFQ": _source_validation(
        summary="Infleqtion 财报中心与 Q1 2026 业绩公告共同验证其量子 sensing 收入和商业化推进。",
        sources=[
            _source("Infleqtion Financial Results", "https://ir.infleqtion.com/financial-information/financial-results", "公司财报"),
            _source("Infleqtion Q1 2026 Results", "https://ir.infleqtion.com/news-events/press-releases/detail/186/infleqtion-reports-record-q1-revenue-as-customer-demand-accelerates", "业绩公告"),
        ],
    ),
}


_A_SHARE_SOURCE_VALIDATIONS: dict[str, dict[str, Any]] = {
    "688498": _source_validation(
        summary="公司年报和业绩快报都验证了 CW 光源与硅光光源进入增长阶段。",
        sources=[
            _source("源杰科技 2024 年报", "https://static.cninfo.com.cn/finalpage/2025-04-26/1223315239.PDF", "公司年报"),
            _source("源杰科技 2025 业绩快报", "http://dataclouds.cninfo.com.cn/shgonggao/hsomarket/2026/20260227/0ce19c8acccc484eab6b690cb177a081.PDF", "业绩快报"),
        ],
    ),
    "688167": _source_validation(
        summary="量子和光通信双主题里都更接近激光/微光学卡点，但仍以高端制造验证为主。",
        sources=[
            _source("天孚通信 2026 年投资者关系记录", "https://static.cninfo.com.cn/finalpage/2026-04-22/1225150075.PDF", "产业链对照"),
            _source("NVIDIA Silicon Photonics 官方产品页", "https://www.nvidia.com/en-gb/networking/products/silicon-photonics/", "官方生态"),
        ],
    ),
    "300308": _source_validation(
        summary="年报与财务决算同时验证了 1.6T 交付、备货和扩产。",
        sources=[
            _source("中际旭创 2025 年报", "http://static.cninfo.com.cn/finalpage/2026-03-31/1225056459.PDF", "公司年报"),
            _source("中际旭创 2025 财务决算", "https://static.cninfo.com.cn/finalpage/2026-03-31/1225056495.PDF", "财务决算"),
        ],
    ),
    "300502": _source_validation(
        summary="官方生态和公司 IR 共同验证了其北美 AI 光模块地位与 2026 年交付延续。",
        sources=[
            _source("NVIDIA Spectrum-X Photonics 官方新闻稿", "https://investor.nvidia.com/news/press-release-details/2025/NVIDIA-Announces-Spectrum-X-Photonics-Co-Packaged-Optics-Networking-Switches-to-Scale-AI-Factories-to-Millions-of-GPUs/default.aspx", "官方新闻稿"),
            _source("新易盛 2026 年投资者关系记录", "http://static.cninfo.com.cn/finalpage/2026-04-24/1225178251.PDF", "投资者关系记录"),
        ],
    ),
    "300394": _source_validation(
        summary="业绩与 IR 均验证了 1.6T 光引擎量产和 CPO 配套开发。",
        sources=[
            _source("天孚通信 2026 年投资者关系记录", "https://static.cninfo.com.cn/finalpage/2026-04-22/1225150075.PDF", "投资者关系记录"),
            _source("天孚通信 2025 财务决算", "https://static.cninfo.com.cn/finalpage/2026-04-08/1225082716.PDF", "财务决算"),
        ],
    ),
    "688313": _source_validation(
        summary="业绩快报与交流纪要验证 AWG 和高速器件受 AI 数通拉动。",
        sources=[
            _source("仕佳光子 2024 业绩快报", "https://static.cninfo.com.cn/finalpage/2025-02-28/1222661167.PDF", "业绩快报"),
            _source("仕佳光子 2026 年投资者关系记录", "http://dataclouds.cninfo.com.cn/shgonggao/investor/2026/20260421/9d5951c23f3c4fb7a215c1f47e097047.PDF", "投资者关系记录"),
        ],
    ),
    "002281": _source_validation(
        summary="年报与业绩说明会都验证了 1.6T 交付与硅光/NPO 储备。",
        sources=[
            _source("光迅科技 2025 年报摘要", "http://static.cninfo.com.cn/finalpage/2026-04-23/1225148211.PDF", "公司年报"),
            _source("光迅科技 2026 年业绩说明会记录", "http://static.cninfo.com.cn/finalpage/2026-05-15/1225308047.PDF", "业绩说明会"),
        ],
    ),
    "688126": _source_validation(
        summary="Soitec 业绩与中国授权延长支持其作为 A 股 SOI 主映射。",
        sources=[
            _source("Soitec FY26 Results", "https://www.soitec.com/home/group/newsroom/press-releases/content/2026/05/27/soitec-reports-fiscal-2026-full-year-results", "公司业绩公告"),
            _source("Soitec 与 NSIG 授权延长", "https://www.soitec.com/home/group/newsroom/press-releases/content/2026/03/13/soitec-and-nsig-to-agree-extension-of-licensing-framework", "官方新闻稿"),
        ],
    ),
    "002428": _source_validation(
        summary="互动平台与权威媒体报道都验证了其磷化铟衬底和扩产逻辑。",
        sources=[
            _source("云南锗业互动平台问答", "https://irm.cninfo.com.cn/ircs/question/questionDetail?questionId=1995277988417691648", "互动平台"),
            _source("证券时报：磷化铟价格与扩产跟踪", "https://stcn.com/article/detail/3930527.html", "权威媒体"),
        ],
    ),
    "600703": _source_validation(
        summary="官网定位与公开出货口径共同验证其外延与高速光芯片承接能力。",
        sources=[
            _source("三安光电官网 About", "https://www.sanan-e.com/about-us", "公司官网"),
            _source("三安光电高速光芯片出货报道", "https://finance.sina.com.cn/jjxw/2026-06-09/doc-iniauzks3246445.shtml", "权威媒体"),
        ],
    ),
    "605358": _source_validation(
        summary="更像高端硅片平台补充映射，SOI 纯度弱于沪硅产业。",
        sources=[
            _source("Soitec FY26 Results", "https://www.soitec.com/home/group/newsroom/press-releases/content/2026/05/27/soitec-reports-fiscal-2026-full-year-results", "行业锚点"),
            _source("Soitec 与 NSIG 授权延长", "https://www.soitec.com/home/group/newsroom/press-releases/content/2026/03/13/soitec-and-nsig-to-agree-extension-of-licensing-framework", "行业锚点"),
        ],
    ),
    "688008": _source_validation(
        summary="年报与新品送样都验证了其连接芯片本体卡位。",
        sources=[
            _source("澜起科技 2025 年报", "https://data.eastmoney.com/notices/detail/688008/AN202603301820868317.html", "公司年报"),
            _source("澜起科技 PCIe 6/CXL 3 Retimer 送样", "https://tech.sina.cn/2025-01-22/detail-inefuxsi7325077.d.html?vt=4", "权威媒体"),
        ],
    ),
    "688515": _source_validation(
        summary="作为高速 PHY / 连接芯片补充映射，适合放在 ALAB 的次主映射位置。",
        sources=[
            _source("澜起科技 2025 年报", "https://data.eastmoney.com/notices/detail/688008/AN202603301820868317.html", "行业对照"),
            _source("Astera PCIe 6 ramp", "https://www.asteralabs.com/news/astera-labs-ramps-production-of-pcie-6-connectivity-portfolio-supercharging-advanced-ai-and-cloud-infrastructure-deployments/", "海外锚点"),
        ],
    ),
    "688702": _source_validation(
        summary="更接近 AI Ethernet fabric 层，适合作为 Broadcom 映射补充。",
        sources=[
            _source("Broadcom FY2025 Results", "https://www.broadcom.com/company/news/financial-releases/63716", "海外锚点"),
            _source("Tomahawk Ultra 发布", "https://www.broadcom.com/company/news/product-releases/63341", "海外锚点"),
        ],
    ),
    "605277": _source_validation(
        summary="通过安费诺链条进入全球 AI 服务器供应链，已经有收入与客户验证。",
        sources=[
            _source("证券日报：新亚电子高速铜缆连接线跟踪", "https://finance.eastmoney.com/a/202605133736167721.html", "权威媒体"),
            _source("证券时报：新亚电子进入安费诺供应链", "https://m.10jqka.com.cn/20260429/c676395292.shtml", "权威媒体"),
        ],
    ),
    "002130": _source_validation(
        summary="年报与互动平台都验证了 224G 稳定交付和 448G 客户验证。",
        sources=[
            _source("沃尔核材 2025 年报", "http://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=12052599", "公司年报"),
            _source("深交所互动易：高速通信线客户结构", "https://ir.p5w.net/question/00012333E8EC8A4E42049E2F8A928271F952.shtml", "互动平台"),
        ],
    ),
    "603986": _source_validation(
        summary="兆易创新年报与利润分配公告共同验证其存储设计平台和经营兑现。",
        sources=[
            _source("兆易创新 2024 年报", "https://static.cninfo.com.cn/finalpage/2025-04-26/1223305062.PDF", "公司年报"),
            _source("兆易创新 2024 年度利润分配预案公告", "http://dataclouds.cninfo.com.cn/shgonggao/2025/2025-04-26/9e5b8eb221b611f09899f010907b9098.pdf", "公司公告"),
        ],
    ),
    "603019": _source_validation(
        summary="中科曙光年报与重大资产重组终止公告共同验证其先进计算平台定位与资本运作进展。",
        sources=[
            _source("中科曙光 2024 年报", "https://www.sse.com.cn/disclosure/listedinfo/announcement/c/new/2025-03-05/603019_20250305_LPGP.pdf", "公司年报"),
            _source("中科曙光 终止重大资产重组公告", "http://dataclouds.cninfo.com.cn/shgonggao/hsomarket/2025/20251209/d8e5cb582694497292b3c85056847166.PDF", "公司公告"),
        ],
    ),
    "300738": _source_validation(
        summary="IDC 资源承接逻辑主要来自算力基础设施建设节奏与机柜、电力配套约束。",
        sources=[
            _source("Nebius Q1 2026 Results", "https://www.nasdaq.com/press-release/nebius-reports-first-quarter-2026-financial-results-2026-05-13", "海外锚点"),
            _source("IEA Data Centre Electricity Use 2026", "https://www.iea.org/news/data-centre-electricity-use-surged-in-2025-even-with-tightening-bottlenecks-driving-a-scramble-for-solutions", "权威机构"),
        ],
    ),
    "688981": _source_validation(
        summary="中芯国际年报与利润分配公告共同验证其先进代工平台的高资本开支属性。",
        sources=[
            _source("中芯国际 2024 年报", "http://dataclouds.cninfo.com.cn/shgonggao/2025/2025-03-28/3c23c74a0af611f0836c5ca721423a28.pdf", "公司年报"),
            _source("中芯国际 2024 年度利润分配方案公告", "http://www.sse.com.cn/disclosure/listedinfo/announcement/c/new/2025-03-28/688981_20250328_VURL.pdf", "公司公告"),
        ],
    ),
    "688347": _source_validation(
        summary="华虹公司业绩公告已验证其特色工艺平台收入增长与高产能利用率。",
        sources=[
            _source("华虹公司 2025Q4/全年业绩公告", "http://static.cninfo.com.cn/finalpage/2026-02-13/1224978931.PDF", "业绩公告"),
            _source("Tower Semiconductor 特色工艺对照", "https://ir.towersemi.com/news-releases/news-release-details/iqe-and-tower-semiconductor-announce-multi-year-inp-epiwafer", "海外对照"),
        ],
    ),
    "688120": _source_validation(
        summary="华海清科年报与业绩预增公告共同验证其 CMP 等高端半导体装备放量。",
        sources=[
            _source("华海清科 2024 年报", "https://www.sse.com.cn/disclosure/listedinfo/announcement/c/new/2025-04-29/688120_20250429_Z8LC.pdf", "公司年报"),
            _source("华海清科 2024 年业绩预增公告", "http://www.sse.com.cn/disclosure/listedinfo/announcement/c/new/2025-01-24/688120_20250124_D1PE.pdf", "业绩预告"),
        ],
    ),
    "300604": _source_validation(
        summary="先进测试与封测装备承接逻辑由 ASE 与 TSMC 的先进封装扩产共同验证。",
        sources=[
            _source("ASE K18B Groundbreaking", "https://www.aseglobal.com/press-room/k18b-groundbreaking-ceremony", "海外锚点"),
            _source("TSMC 2024 Annual Report", "https://investor.tsmc.com/static/annualReports/2024/english/index.html", "海外年报"),
        ],
    ),
    "600118": _source_validation(
        summary="中国卫星年报摘要与利润分配公告共同验证其卫星系统平台属性和行业景气判断。",
        sources=[
            _source("中国卫星 2024 年报摘要", "https://www.sse.com.cn/disclosure/listedinfo/announcement/c/new/2025-04-12/600118_20250412_FMIH.pdf", "年报摘要"),
            _source("中国卫星 2024 年度利润分配方案公告", "https://www.sse.com.cn/disclosure/listedinfo/announcement/c/new/2025-04-12/600118_20250412_6GHI.pdf", "公司公告"),
        ],
    ),
    "600406": _source_validation(
        summary="国电南瑞年报与半年度评估报告共同验证其电网自动化与订单景气度。",
        sources=[
            _source("国电南瑞 2024 年报", "https://www.sse.com.cn/disclosure/listedinfo/announcement/c/new/2025-04-29/600406_20250429_7MZS.pdf", "公司年报"),
            _source("国电南瑞 2025 半年度评估报告", "http://dataclouds.cninfo.com.cn/shgonggao/2025/2025-08-28/2c62cfb8832611f086b3fa163e957f7a.pdf", "评估报告"),
        ],
    ),
    "600111": _source_validation(
        summary="北方稀土年报与业绩说明会公告共同验证其冶炼分离主导地位与行业景气判断。",
        sources=[
            _source("北方稀土 2024 年报", "https://www.sse.com.cn/disclosure/listedinfo/announcement/c/new/2025-04-19/600111_20250419_RRGE.pdf", "公司年报"),
            _source("北方稀土 业绩暨现金分红说明会公告", "https://www.sse.com.cn/disclosure/listedinfo/announcement/c/new/2025-04-29/600111_20250429_5FHL.pdf", "公司公告"),
        ],
    ),
    "688160": _source_validation(
        summary="权威媒体与经营数据页面共同验证其机器人业务高增长与关节平台布局。",
        sources=[
            _source("证券日报：步科股份机器人业务高增长", "http://m.zqrb.cn/gscy/ggkx/2026-06-03/A1780473132677.html", "权威媒体"),
            _source("步科股份经营总结", "https://quote.cfi.cn/jyzj/105630/688160.html", "经营数据"),
        ],
    ),
    "688027": _source_validation(
        summary="国盾量子年报与业绩预告共同验证其量子通信、量子计算和量子精密测量业务进展。",
        sources=[
            _source("国盾量子 2024 年报", "https://www.sse.com.cn/disclosure/listedinfo/announcement/c/new/2025-03-26/688027_20250326_ZRKI.pdf", "公司年报"),
            _source("国盾量子 2024 年业绩预告", "http://dataclouds.cninfo.com.cn/shgonggao/2025/2025-01-18/d75cef05d4bc11efb43ffa163e957f7a.pdf", "业绩预告"),
        ],
    ),
}


_PROJECT_SELECTION_METRICS: dict[str, dict[str, Any]] = {
    "SIVE": {
        "selection_reason": _selection_reason(
            "符合 Serenity 方法，因为它站在 laser / external light source / CPO upstream 这一层，真正卡的是上游光源而不是模组出货。",
            "它更像上游 photonics choke point 的前瞻锚点，而不是单纯跟随 AI 光模块景气的 beta。",
        ),
        "scarcity_view": _scarcity_view("高", "外部光源和上游激光一旦进入量产链，供应商数量少、验证慢、替代更慢。"),
        "capacity_view": _capacity_view("扩产难", "需要客户验证、光学良率和系统导入同时推进，扩产不是简单加设备。"),
        "pricing_view": _pricing_view("有涨价基础", "若外部光源路线成立，上游光源更容易在供需偏紧时获得议价。"),
        "segment_market_view": _segment_market_view("对应外部光源 / 上游激光环节可按数十亿美元级理解。", "公司份额仍偏早期，当前更适合按低个位数潜在份额理解。", "早期卡位"),
    },
    "LITE": {
        "selection_reason": _selection_reason(
            "符合 Serenity 方法，因为它不是单一模组厂，而是光器件、激光与 CPO 平台能力的综合承接者。",
            "市场看它时容易只看光模块景气，但更关键的是它在器件平台和光引擎升级中的位置。",
        ),
        "scarcity_view": _scarcity_view("中高", "多产品线激光与器件平台能力难快速复制，尤其在高端 datacom photonics。"),
        "capacity_view": _capacity_view("中高", "平台扩产不仅是产能，还包含高端产品 mix、验证与交付节奏。"),
        "pricing_view": _pricing_view("有涨价基础", "高端器件与平台型产品通常比普通模组更有价格传导能力。"),
        "segment_market_view": _segment_market_view("高端光器件 / 光引擎平台可按百亿美元级别理解。", "公司份额可按中高个位数到低双位数理解。", "中高"),
    },
    "AAOI": {
        "selection_reason": _selection_reason(
            "符合 Serenity 方法，因为它横跨激光与 transceiver 过渡层，适合观察路线切换时的重新定价。",
            "它不是最纯的上游卡点，但比单一模组股更接近激光和光引擎的桥梁层。",
        ),
        "scarcity_view": _scarcity_view("中", "过渡层位置有价值，但稀缺性弱于真正的上游光芯片与外部光源。"),
        "capacity_view": _capacity_view("中高", "既要看激光器件爬坡，也要看 transceiver 平台承接，扩产是双变量。"),
        "pricing_view": _pricing_view("有涨价基础", "若高端光互连需求持续，桥梁层产品也有价格修复空间。"),
        "segment_market_view": _segment_market_view("对应激光 + transceiver 过渡层可按数十亿美元级理解。", "公司份额更适合按中个位数理解。", "中"),
    },
    "COHR": {
        "selection_reason": _selection_reason(
            "符合 Serenity 方法，因为它是激光与光器件平台型样本，能承接多条 AI 光互连需求。",
            "它不是单点 choke point，但平台厚度让它更像上游基础设施提供者。",
        ),
        "scarcity_view": _scarcity_view("中高", "激光与 datacom photonics 平台壁垒高，但多业务并行也会稀释纯度。"),
        "capacity_view": _capacity_view("中高", "平台扩产依赖高端器件验证与产线协同，不是单一 SKU 放量。"),
        "pricing_view": _pricing_view("有涨价基础", "高端激光与器件平台在供需紧张时比模组更有议价能力。"),
        "segment_market_view": _segment_market_view("激光与 datacom photonics 平台可按百亿美元级理解。", "公司份额可按中个位数到低双位数理解。", "中高"),
    },
    "POET": {
        "selection_reason": _selection_reason(
            "符合 Serenity 方法，因为它押的是 optical engine / external light source 新路线，而不是成熟模组扩产。",
            "真正的关注点是路线验证后，它会不会成为少数被客户接受的平台方案。"),
        "scarcity_view": _scarcity_view("中高", "若路线成立，稀缺性会快速上升，但目前仍处于前瞻验证阶段。"),
        "capacity_view": _capacity_view("扩产难", "新路线需要客户导入、模块兼容与平台验证，不是传统器件平滑扩产。"),
        "pricing_view": _pricing_view("待验证", "要先看到路线成立，价格传导才有明确基础。"),
        "segment_market_view": _segment_market_view("对应 optical engine / external light source 新平台，市场当前可按数十亿美元早期机会理解。", "公司份额仍处于验证期，适合按早期潜在份额理解。", "早期卡位"),
    },
    "AXTI": {
        "selection_reason": _selection_reason(
            "符合 Serenity 方法，因为它站在 InP / III-V 衬底这种更上游的材料 choke point。",
            "市场常追终端器件，但真正难替代的地方往往在基底与材料供给。"),
        "scarcity_view": _scarcity_view("高", "InP / III-V 衬底供应商少、验证周期长、替代成本高。"),
        "capacity_view": _capacity_view("扩产难", "材料纯度、良率和下游认证共同决定扩产速度。"),
        "pricing_view": _pricing_view("有涨价基础", "材料端一旦供给偏紧，价格传导通常比下游更直接。"),
        "segment_market_view": _segment_market_view("InP / III-V 基底环节可按数十亿美元级理解。", "公司份额更适合按中个位数到低双位数理解。", "中高"),
    },
    "IQE": {
        "selection_reason": _selection_reason(
            "符合 Serenity 方法，因为它卡在 epiwafer 和外延前段，这一层比终端品牌更接近真实瓶颈。",
            "外延层常被低估，但一旦 AI 数据中心光子需求向前段传导，价值会先在这里体现。"),
        "scarcity_view": _scarcity_view("高", "外延前段属于制造前准备层，客户切换慢，工艺验证成本高。"),
        "capacity_view": _capacity_view("扩产难", "外延片扩产受工艺、良率和客户认证共同约束。"),
        "pricing_view": _pricing_view("有涨价基础", "若前段供给收紧，外延层比终端更容易体现结构性议价。"),
        "segment_market_view": _segment_market_view("高端 epiwafer / 外延前段可按数十亿美元级理解。", "公司份额可按中个位数理解。", "中"),
    },
    "SOI": {
        "selection_reason": _selection_reason(
            "符合 Serenity 方法，因为它是高端基底平台，不依赖单一终端景气，而是多路线共用的底层供给者。",
            "真正稀缺的不是某个器件，而是高端 SOI / silicon photonics substrate 本身。"),
        "scarcity_view": _scarcity_view("高", "高端 SOI 基底供应商少、验证长、切换成本高。"),
        "capacity_view": _capacity_view("扩产难", "高端基底扩产受良率、客户验证和资本投入共同约束。"),
        "pricing_view": _pricing_view("有涨价基础", "若 silicon photonics 与高端器件共同放量，基底层更容易体现结构性溢价。"),
        "segment_market_view": _segment_market_view("Photonics-SOI / 高端基底市场可按百亿美元级理解。", "公司份额可按高份额平台理解。", "高"),
    },
    "AVGO": {
        "selection_reason": _selection_reason(
            "符合 Serenity 方法，因为它卡在 AI Ethernet switch 和 scale-up fabric，是真正接近系统扩容约束的层。",
            "比起只卖线缆和连接器，它更接近网络 silicon 与 AI 集群的核心控制点。"),
        "scarcity_view": _scarcity_view("高", "AI Ethernet switch 与 fabric 需要长期技术积累和客户平台导入。"),
        "capacity_view": _capacity_view("中高", "扩容更依赖产品节奏和客户平台切换，不是简单扩产线。"),
        "pricing_view": _pricing_view("有涨价基础", "网络中枢一旦成为集群瓶颈，更有能力维持高毛利与平台溢价。"),
        "segment_market_view": _segment_market_view("AI Ethernet switch / scale-up fabric 可按数百亿美元级理解。", "公司份额适合按高份额龙头理解。", "高"),
    },
    "ALAB": {
        "selection_reason": _selection_reason(
            "符合 Serenity 方法，因为它站在 PCIe/CXL Retimer 和连接协议层，直接受益于系统复杂度抬升。",
            "真正的卡点不是整机，而是互连标准升级后的底层连接芯片。"),
        "scarcity_view": _scarcity_view("高", "协议层与连接芯片验证重、导入慢，替代难度高。"),
        "capacity_view": _capacity_view("中高", "扩张更多受客户平台认证与设计导入节奏影响。"),
        "pricing_view": _pricing_view("有涨价基础", "高性能互连芯片一旦进入平台，价格弹性通常强于中游材料。"),
        "segment_market_view": _segment_market_view("AI 连接芯片 / Retimer / Switch 市场可按百亿美元级理解。", "公司份额可按中低双位数成长样本理解。", "中高"),
    },
    "CRDO": {
        "selection_reason": _selection_reason(
            "符合 Serenity 方法，因为它是 AEC 和高速铜互连最直接的纯主题样本之一。",
            "它卡住的是高速铜互连标准变化，而不是泛网络设备景气。"),
        "scarcity_view": _scarcity_view("中高", "AEC DSP 和高速铜互连方案壁垒高于普通线缆，但弱于交换芯片本体。"),
        "capacity_view": _capacity_view("中高", "真正难的是 hyperscaler 导入与代际切换，不是线缆产线本身。"),
        "pricing_view": _pricing_view("有涨价基础", "高速 AEC 一旦形成标准优势，价格传导能力强于普通铜缆。"),
        "segment_market_view": _segment_market_view("AEC / 高速铜互连可按数十亿美元到百亿美元级理解。", "公司份额可按中高个位数到低双位数理解。", "中高"),
    },
    "SNDK": {
        "selection_reason": _selection_reason(
            "符合 Serenity 方法，因为它押的不是普通消费存储，而是 NAND 重定价、HBM shortage 外溢与 memory cycle 修复。",
            "真正的变化是 AI 已把存储从周期品推向战略资产，价格修复和资本开支纪律会先在这一层体现。"),
        "scarcity_view": _scarcity_view("中高", "成熟 NAND 本身不是最稀缺，但当 HBM 与高性能 DRAM 吸走资本开支后，传统存储供给也会被动收紧。"),
        "capacity_view": _capacity_view("中高", "要看减产、复产和先进产品 mix 调整，真正变量是资本开支纪律而不是单纯扩线。"),
        "pricing_view": _pricing_view("有涨价基础", "当前更像价格先行而非单纯出货恢复，HBM shortage 外溢会强化存储链的重定价逻辑。"),
        "segment_market_view": _segment_market_view("NAND / 企业级 SSD / AI 存储可按数百亿美元级理解。", "公司份额适合按全球重要存储厂商理解。", "高"),
    },
    "NBIS": {
        "selection_reason": _selection_reason(
            "符合 Serenity 方法，因为它卡在 neocloud 供给缺口与 GPU 真正上电交付这一层，而不是传统云软件叙事。",
            "真正稀缺的不是 GPU 名义订单，而是 active power、contracted power 与把算力资源变成可交付服务的能力。"),
        "scarcity_view": _scarcity_view("高", "可通电机房、GPU 供给、网络与调度软件一起构成稀缺层。"),
        "capacity_view": _capacity_view("扩产难", "扩容取决于 MW/GW 上电节奏、机房 energization 和供应链协同，不是签了订单就能立刻兑现。"),
        "pricing_view": _pricing_view("有涨价基础", "在供给缺口持续时，GPU 云租赁、存储与网络附加服务都具备较强议价基础。"),
        "segment_market_view": _segment_market_view("AI neocloud / GPU 租赁 / AI 基础设施可按数百亿美元级理解。", "公司份额仍适合按高成长但非龙头理解。", "中高"),
    },
    "TSM": {
        "selection_reason": _selection_reason(
            "符合 Serenity 方法，因为它是 AI 半导体最硬的 foundry 锚点，卡在 N2/N3 与先进封装产能中枢。",
            "市场容易只看 GPU 需求，但真正节奏决定权在先进逻辑代工与先进封装的产能配置。"),
        "scarcity_view": _scarcity_view("高", "N2/N3 与先进封装都需要长期工艺积累、客户协同和极高资本门槛。"),
        "capacity_view": _capacity_view("扩产难", "扩产要同步解决新节点良率、厂房、设备与客户导入，远不是普通制造业加产线。"),
        "pricing_view": _pricing_view("有涨价基础", "先进节点 ASP 与先进封装溢价共同支撑价格传导，是 AI 资本开支最强承接层。"),
        "segment_market_view": _segment_market_view("先进逻辑代工与先进封装可按数千亿美元级半导体核心环节理解。", "公司份额适合按全球绝对龙头理解。", "高"),
    },
    "TSEM": {
        "selection_reason": _selection_reason(
            "符合 Serenity 方法，因为它不是先进逻辑，而是 specialty foundry、模拟、功率与 photonics 工艺的稳定卡位。",
            "真正难替代的是特色工艺 know-how、客户认证和长期产品生命周期，而不是最先进制程的 headline。"),
        "scarcity_view": _scarcity_view("中高", "特色工艺壁垒来自车规、工业和模拟/功率验证链条，切换成本高。"),
        "capacity_view": _capacity_view("中高", "扩产要看客户认证、产品 mix 与成熟工艺利用率，而不是单一节点追赶。"),
        "pricing_view": _pricing_view("结构升级", "特色工艺更偏客户粘性和 mix 优化，不一定大涨价，但可持续抬升利润率。"),
        "segment_market_view": _segment_market_view("Specialty foundry / 模拟 / 功率 / photonics 工艺可按数百亿美元级理解。", "公司份额适合按细分重要平台理解。", "中高"),
    },
    "XFAB": {
        "selection_reason": _selection_reason(
            "符合 Serenity 方法，因为它押的是 silicon photonics 与 specialty foundry 的细分制造错配。",
            "市场常忽略这类不显眼工艺，但如果硅光与模拟/功率需求持续扩张，价值会先在这种细分代工层体现。"),
        "scarcity_view": _scarcity_view("中高", "硅光与特色工艺平台供应商少，导入周期长。"),
        "capacity_view": _capacity_view("中高", "扩产更依赖客户组合与高附加值产品导入，而不是简单上 wafer 数。"),
        "pricing_view": _pricing_view("结构升级", "价格弹性更多来自高附加值工艺占比提升，而非纯现货涨价。"),
        "segment_market_view": _segment_market_view("Silicon photonics / specialty foundry 可按数十亿美元到百亿美元级理解。", "公司份额适合按细分 niche 平台理解。", "中"),
    },
    "TOWA": {
        "selection_reason": _selection_reason(
            "符合 Serenity 方法，因为它更接近 CoWoS / HBM 时代先进封装设备 choke point，而不是普通后道设备。",
            "封装已经从尾端配套升级成 AI 芯片能否交付的放行阀，设备环节会先被重估。"),
        "scarcity_view": _scarcity_view("高", "先进封装设备需要工艺 know-how、客户验证和良率积累，供应商数量少。"),
        "capacity_view": _capacity_view("扩产难", "设备放量取决于客户 capex、验证节奏和先进封装工艺导入速度。"),
        "pricing_view": _pricing_view("有涨价基础", "当 CoWoS / HBM 产能偏紧时，关键设备更容易维持高毛利和溢价。"),
        "segment_market_view": _segment_market_view("先进封装设备 / HBM 后段制造可按数十亿美元到百亿美元级理解。", "公司份额适合按细分设备龙头理解。", "中高"),
    },
    "LPK": {
        "selection_reason": _selection_reason(
            "符合 Serenity 方法，因为它押的是玻璃基板与先进封装新材料路线，而不是成熟封装扩产。",
            "真正的吸引力不在现有体量，而在于一旦路线切换成立，材料与设备链会被整体重估。"),
        "scarcity_view": _scarcity_view("中高", "玻璃基板路线仍早，但若验证成功，供应商与工艺 know-how 都会很稀缺。"),
        "capacity_view": _capacity_view("扩产难", "路线导入要经过材料、制程、封装与客户共研验证，不是现有载板线平移。"),
        "pricing_view": _pricing_view("验证期", "当前更像路线验证期估值弹性，而不是成熟产品的实质涨价。"),
        "segment_market_view": _segment_market_view("玻璃基板 / 先进封装新材料可按数十亿美元潜在空间理解。", "公司份额仍适合按早期潜在份额理解。", "早期卡位"),
    },
    "RKLB": {
        "selection_reason": _selection_reason(
            "符合 Serenity 方法，因为它同时卡在发射频次、卫星系统交付和平台化延展，而不是一次性事件驱动。",
            "真正稀缺的不是火箭概念，而是 75次成功任务、200+ 航天器交付背后的系统级执行能力。"),
        "scarcity_view": _scarcity_view("高", "高频次稳定发射与航天系统垂直整合都需要极长时间积累，替代慢。"),
        "capacity_view": _capacity_view("扩产难", "扩产取决于发射节奏、产线爬坡和整星制造能力，不是单点部件扩产。"),
        "pricing_view": _pricing_view("有涨价基础", "专属发射、系统交付与政府任务都能提供比普通军工配套更强的定价能力。"),
        "segment_market_view": _segment_market_view("小型发射 + 航天系统交付可按数十亿美元级理解。", "公司份额适合按全球少数系统级玩家理解。", "中高"),
    },
    "-": {
        "selection_reason": _selection_reason(
            "符合 Serenity 方法，因为它是商业航天的系统级锚点，定义了发射、卫星互联网和产业链的最高边界。",
            "与其把它当比较对象，不如把它当作反推 A 股应该贴近哪些真实 choke point 的行业坐标。"),
        "scarcity_view": _scarcity_view("高", "发射、星座、终端和系统集成一体化能力在全球都极稀缺。"),
        "capacity_view": _capacity_view("扩产难", "任何新增能力都牵涉系统工程、供应链、审批和资本密集投入。"),
        "pricing_view": _pricing_view("有涨价基础", "系统级能力一旦形成规模优势，通常有更强议价与生态定价权。"),
        "segment_market_view": _segment_market_view("商业航天系统级市场可按数百亿美元到千亿美元级长期空间理解。", "公司份额更适合按行业锚定者理解。", "高"),
    },
    "XLU": {
        "selection_reason": _selection_reason(
            "符合 Serenity 方法，因为它不是传统防御型公用事业，而是 AI power bottleneck 的行业锚点。",
            "当数据中心用电与电网 capex 进入新周期，真正的主线是容量、电网和并网约束，而不是高股息叙事。"),
        "scarcity_view": _scarcity_view("高", "变压器、燃机、并网容量和电网投资节奏共同构成 AI 扩容约束。"),
        "capacity_view": _capacity_view("扩产难", "新电力供给受审批、并网、设备交期和 MW 落地节奏共同限制。"),
        "pricing_view": _pricing_view("有涨价基础", "容量电价、设备提价和电力供给紧张都会带来结构性价格传导。"),
        "segment_market_view": _segment_market_view("AI 电力基础设施 / 公用事业 capex / 电网设备可按数百亿美元级理解。", "更适合按行业锚点而非单点份额理解。", "高"),
    },
    "VNP": {
        "selection_reason": _selection_reason(
            "符合 Serenity 方法，因为它押的是关键矿物与供应链安全，而不是普通有色价格波动。",
            "真正值得看的是锑、稀土、钨、铜这些供给受约束且具战略属性的矿种，而不是简单追涨资源价格。"),
        "scarcity_view": _scarcity_view("高", "关键矿物的稀缺性常来自分离、冶炼、配额和地缘约束，而不只是资源量本身。"),
        "capacity_view": _capacity_view("扩产难", "资源开发要跨越许可、融资、建设和回收率多个环节，产能兑现很慢。"),
        "pricing_view": _pricing_view("有涨价基础", "出口管制、价格底和战略采购都可能放大关键矿物的定价权。"),
        "segment_market_view": _segment_market_view("关键矿物 / 稀土磁材 / 锑 / 钨 / 铜可按数十亿美元到百亿美元级理解。", "更适合按战略矿种组合锚点理解。", "高"),
    },
    "VPG": {
        "selection_reason": _selection_reason(
            "符合 Serenity 方法，因为它卡在高精度 sensing、力控与机器人手部这些高附加值 choke point。",
            "与其看整机，不如看那些在高自由度和复杂工况下仍难被替代的精密传感器。"),
        "scarcity_view": _scarcity_view("中高", "高精度 sensing 与力控验证重、客户切换慢，是机器人里更接近稀缺层的部件。"),
        "capacity_view": _capacity_view("中高", "扩产不只看产能，还要看精度、一致性和工业客户验证。"),
        "pricing_view": _pricing_view("有涨价基础", "高附加值传感器更依赖性能溢价，价格压力通常小于低端执行件。"),
        "segment_market_view": _segment_market_view("高精度传感器 / 力控 / 机器人感知环节可按数十亿美元级理解。", "公司份额适合按细分高端玩家理解。", "中"),
    },
    "AEVA": {
        "selection_reason": _selection_reason(
            "符合 Serenity 方法，因为它押的是机器人和 physical AI 的感知升级，而不是单纯自动驾驶叙事。",
            "FMCW LiDAR 的速度信息和更强空间理解能力，让它更接近下一代机器人感知 choke point。"),
        "scarcity_view": _scarcity_view("中高", "FMCW LiDAR 方案复杂、供应商少，但商业化仍在验证期。"),
        "capacity_view": _capacity_view("中高", "扩产取决于客户导入、方案定型和量产良率，不是普通传感器扩产。"),
        "pricing_view": _pricing_view("验证期", "当前更像路线验证和平台卡位，真正价格传导要等机器人量产。"),
        "segment_market_view": _segment_market_view("机器人感知 / FMCW LiDAR 可按数十亿美元潜在空间理解。", "公司份额适合按早期路线玩家理解。", "早期卡位"),
    },
    "SSYS": {
        "selection_reason": _selection_reason(
            "符合 Serenity 方法，因为它承接机器人骨架、轻量结构与 3D 打印材料/工艺验证，不是普通制造周期股。",
            "真正吸引人的地方是量产初期被验证过的结构件与制造方案，而不是 3D 打印概念本身。"),
        "scarcity_view": _scarcity_view("中", "结构件与材料工艺有壁垒，但稀缺性仍弱于减速器、传感器和执行器。"),
        "capacity_view": _capacity_view("中高", "扩产要看材料认证、制造效率和大客户导入。"),
        "pricing_view": _pricing_view("结构升级", "利润改善更依赖高附加值结构件和工业级方案占比提升。"),
        "segment_market_view": _segment_market_view("机器人结构件 / 3D 打印制造方案可按数十亿美元级理解。", "公司份额适合按结构工艺平台理解。", "中"),
    },
    "INFQ": {
        "selection_reason": _selection_reason(
            "符合 Serenity 方法，因为它更接近量子 sensing 收入和工程化量子计算路径，而不是 science project 式概念。",
            "市场容易追逐比特数 headline，但真正的价值来自量子 sensing、政府订单和设备化进展。"),
        "scarcity_view": _scarcity_view("中高", "量子工程化供应商少，系统、制冷、测控和材料都卡住放量节奏。"),
        "capacity_view": _capacity_view("扩产难", "量子硬件仍是高单价、小批量、项目制交付，工程化速度远慢于需求热度。"),
        "pricing_view": _pricing_view("验证期", "短期更像高单价科研装备，量产型价格传导仍需等待更多商业化验证。"),
        "segment_market_view": _segment_market_view("量子 sensing / 量子硬件系统可按数十亿美元早期市场理解。", "公司份额适合按前沿路线重要玩家理解。", "早期卡位"),
    },
    "ALRIB": {
        "selection_reason": _selection_reason(
            "符合 Serenity 方法，因为它押的是 MBE 和量子器件制造前段，而不是应用端热闹概念。",
            "如果量子器件真的进入放量，最先被重估的往往是前段精密制造设备而不是应用软件。"),
        "scarcity_view": _scarcity_view("高", "前段精密制造设备、真空与材料控制都属于典型卖铲人稀缺层。"),
        "capacity_view": _capacity_view("扩产难", "设备放量要经过极长研发、验证与客户导入周期。"),
        "pricing_view": _pricing_view("有涨价基础", "一旦进入前沿科研和工程化量产链，高端设备通常具备较强溢价。"),
        "segment_market_view": _segment_market_view("MBE / 量子器件前段制造设备可按数十亿美元级理解。", "公司份额适合按精密设备锚点理解。", "中"),
    },
}


_MATCH_SELECTION_METRICS: dict[str, dict[str, Any]] = {
    "688498": {
        "selection_reason": _selection_reason(
            "符合，因为它是 A 股里最接近 CW / EML 光芯片与外部光源的上游卡位之一，100G EML 已完成验证，200G EML 已进入客户验证。",
            "Lumentum 已公开验证 EML 仍处于 demand outpace supply，源杰更接近这层上游 choke point，而不是模组 beta。",
        ),
        "scarcity_view": _scarcity_view("高", "上游光芯片供应商少、验证慢、替代成本高，且海外已验证 EML 仍是 1.6T/CPO 前夜的真实紧缺层。"),
        "capacity_view": _capacity_view("扩产难", "扩产受外延良率、老化测试、客户验证和高端产品导入共同约束，真正瓶颈不是加设备而是验证。"),
        "pricing_view": _pricing_view("有涨价基础", "上游核心光芯片在供需偏紧时更容易维持议价，若 200G EML 进入放量，量价弹性都会先体现在这一层。"),
        "market_cap_research": _market_cap_research("当前更适合按 100 亿级以上上游器件票理解。", "若硅光光源继续兑现，可上看更高平台型估值。"),
        "segment_market_view": _segment_market_view("若以 2026 年 AI 光模块市场约 260亿美元 为锚，上游 CW / EML 光芯片是其中最紧的关键子环节，可按数十亿美元级理解。", "公司份额仍适合按中个位数理解，但在国产高端 CW / EML 链条里更接近早期核心卡位。", "中"),
    },
    "688167": {
        "selection_reason": _selection_reason("符合，因为它承接微光学 / 激光相关工艺，已在 CPO 四大环节布局，并有产品完成验证后进入小批量供应。", "公司围绕 ELSFP、FAU、PIC-FAU 两端形成四大环节布局，支持 1.6T、3.2T 等速率，比纯配套更靠近关键光学工艺。"),
        "scarcity_view": _scarcity_view("中高", "高端微光学工艺壁垒较高，但最终稀缺性取决于量产验证。"),
        "capacity_view": _capacity_view("扩产难", "扩产受精密制造、客户导入与工艺稳定性约束，当前更接近从验证走向小批量供应。"),
        "pricing_view": _pricing_view("待验证", "价格能力更多取决于是否真正进入核心量产链。"),
        "market_cap_research": _market_cap_research("当前更适合按高端光学制造平台理解。", "若进入更明确核心段，估值中枢仍有抬升空间。"),
        "segment_market_view": _segment_market_view("微光学 / 激光相关环节覆盖可插拔、CPO 与 OCS，支持 1.6T、3.2T 等速率，可按数十亿美元级理解。", "公司份额适合按低个位数到中个位数理解。", "中"),
    },
    "688313": {
        "selection_reason": _selection_reason("符合，因为它站在 AWG / 耦合 / 平行光组件等关键配套层，1.6T 光模块用 AWG 芯片及组件已实现小批量出货。", "虽非最上游 choke point，但它同时覆盖 AWG、FAU、MT-FA 等关键配套，是 CPO 扩散阶段的重要承接层。"),
        "scarcity_view": _scarcity_view("中", "配套层有技术门槛，但稀缺性弱于上游光芯片。"),
        "capacity_view": _capacity_view("中高", "扩产取决于客户验证和高端器件良率，1.6T AWG 与 MT-FA 当前更接近从验证走向小批量释放。"),
        "pricing_view": _pricing_view("有涨价基础", "高端配套器件在新平台导入初期具备一定议价能力。"),
        "market_cap_research": _market_cap_research("当前更适合按中小市值扩散受益样本理解。", "若高速器件持续放量，可往更高器件平台估值切换。"),
        "segment_market_view": _segment_market_view("AWG / FAU / 无源器件可按数十亿美元级理解。", "公司份额适合按中个位数理解。", "中"),
    },
    "300394": {
        "selection_reason": _selection_reason("符合，因为它在 FAU、ELS、光引擎和 CPO 配套上更接近中期卡点，业绩说明会已验证 1.6T 光引擎量产。", "比纯模块更贴近光引擎和器件平台，兼具平台属性与高附加值，且当前已经出现量产与缺料并存。"),
        "scarcity_view": _scarcity_view("中高", "高端光引擎与耦合器件壁垒高，客户切换慢，当前又叠加个别核心物料缺料，说明它不只是讲故事。"),
        "capacity_view": _capacity_view("扩产难", "扩产受高端产品 mix、客户导入和精密制造良率共同约束。"),
        "pricing_view": _pricing_view("有涨价基础", "高附加值 CPO 配套比传统模组更有价格传导能力，但利润改善更多仍来自结构升级和高端产品占比提升。"),
        "market_cap_research": _market_cap_research("当前更适合按中大市值器件平台理解。", "若 1.6T 与 CPO 配套持续上量，可切换到更高平台估值。"),
        "segment_market_view": _segment_market_view("FAU / ELS / 光引擎平台本身不是最大收入池，但它卡在 1.6T 与 CPO 量产配套层，可按数十亿美元级理解。", "公司份额适合按中高个位数到低双位数理解。", "中高"),
    },
    "002281": {
        "selection_reason": _selection_reason("符合，因为它是国内少数兼具光芯片、器件与模块的一体化平台，Omdia 口径下全球光器件份额 5.9%，且 1.6T 已具备批量交付能力。", "Omdia 份额、1.6T 批量交付和芯片自供率提升三条线能闭环，虽然不如纯上游光芯片直接，但平台属性强、承接面广。"),
        "scarcity_view": _scarcity_view("中高", "平台型一体化能力难复制，但业务面宽会稀释纯度。"),
        "capacity_view": _capacity_view("中高", "扩产取决于 1.6T、硅光与国内客户导入的共同进度。"),
        "pricing_view": _pricing_view("有涨价基础", "高端光芯片和新代际模块导入时具备一定议价基础。"),
        "market_cap_research": _market_cap_research("当前更适合按一体化光通信平台理解。", "若硅光和 1.6T 比重上升，可看更高平台估值。"),
        "segment_market_view": _segment_market_view("光芯片+器件+模块平台可按百亿美元级别行业理解。", "Omdia 口径全球光器件份额 5.9%，全球第五，数通光器件全球第四。", "中"),
    },
    "300308": {
        "selection_reason": _selection_reason("符合，因为它是当前 800G/1.6T 可插拔模块最强现金流映射之一，已经站在北美 AI 光模块主赛道中央。", "虽然不是最上游卡点，但 800G/1.6T 的客户认证、交付能力和现金流兑现都极强。"),
        "scarcity_view": _scarcity_view("中", "模组层稀缺性弱于光芯片和基底，但客户认证与规模交付壁垒仍在。"),
        "capacity_view": _capacity_view("中高", "扩产更多取决于客户订单、海外产能与交付节奏。"),
        "pricing_view": _pricing_view("价格传导弱", "模组层更容易受到价格竞争影响，利润改善更多来自 800G/1.6T 结构升级和高端产品 mix，而不是单纯涨价。"),
        "market_cap_research": _market_cap_research("当前更适合按大市值光模块龙头理解。", "若 1.6T 持续兑现，估值中枢仍有抬升空间。"),
        "segment_market_view": _segment_market_view("800G/1.6T 可插拔模块可按百亿美元级理解。", "公司份额适合按全球中高份额理解。", "高"),
    },
    "300502": {
        "selection_reason": _selection_reason("符合，因为它是北美 AI 光模块链里最确定的国内交付样本之一，1.6T 产品订单相对去年大幅增长并预计逐季快速增长。", "更偏景气兑现层，但强在交付和客户验证，同时已覆盖可插拔、LPO/LRO、XPO、NPO 与 CPO 等多路线布局。"),
        "scarcity_view": _scarcity_view("中", "稀缺性主要来自客户认证与交付能力，而非最上游材料。"),
        "capacity_view": _capacity_view("中高", "扩产取决于订单延续、北美客户节奏和海外制造承接，公司已通过锁定备货、预付货款和泰国基地扩产保障 2027-2028 年物料供应。"),
        "pricing_view": _pricing_view("价格传导弱", "模组层易受价格竞争和速率切换影响，但利润改善仍可来自 1.6T 放量、硅光产品占比提升和产品结构升级。"),
        "market_cap_research": _market_cap_research("当前更适合按中大市值高弹性模块龙头理解。", "若高端速率持续放量，可看更高景气中枢。"),
        "segment_market_view": _segment_market_view("高速光模块市场可按百亿美元级理解。", "公司份额适合按全球中高份额理解。", "高"),
    },
    "600703": {
        "selection_reason": _selection_reason("符合，因为它承接 III-V 材料、外延和高速光芯片，100G EML 已推出，数据中心高速 PD 已批量出货。", "CW光源产品已通过海外头部客户认证，兼有材料与器件延展，更像平台型外延与光芯片映射。"),
        "scarcity_view": _scarcity_view("中高", "平台型能力强，覆盖材料、外延、光芯片与器件，但业务较宽，纯度弱于单一材料 choke point。"),
        "capacity_view": _capacity_view("扩产难", "高端外延与光芯片扩产受工艺、良率和客户导入共同约束。"),
        "pricing_view": _pricing_view("有涨价基础", "若高端化合物半导体供给收紧，平台产品更容易体现结构性议价。"),
        "market_cap_research": _market_cap_research("当前更适合按大市值化合物半导体平台理解。", "若高端光芯片收入占比抬升，可切换更高成长估值。"),
        "segment_market_view": _segment_market_view("III-V 材料与外延平台可按数十亿美元级理解。", "公司份额适合按中高个位数理解。", "中高"),
    },
    "002428": {
        "selection_reason": _selection_reason("符合，因为它更纯地映射磷化铟 / 材料链，是 Serenity 偏好的材料 choke point，控股子公司已批量供货磷化铟晶片。", "比平台股更接近关键材料层，且近期下游需求快速增长、公司已批量供货并推进扩产，是少数有现实兑现抓手的材料映射。"),
        "scarcity_view": _scarcity_view("高", "关键化合物半导体材料供应更稀缺，替代更慢。"),
        "capacity_view": _capacity_view("扩产难", "受原料、良率和下游验证共同约束，现有高品质磷化铟单晶片项目计划建设期 18个月，扩产并不快。"),
        "pricing_view": _pricing_view("有涨价基础", "材料端供给紧时通常更容易直接涨价，公司已公开表示近期下游对磷化铟晶片需求快速增长且价格有所上涨。"),
        "market_cap_research": _market_cap_research("当前更适合按小中市值关键材料样本理解。", "若材料属性被重新定价，估值弹性会更陡。"),
        "segment_market_view": _segment_market_view("磷化铟 / 关键材料环节可按数十亿美元级理解。", "公司份额适合按中个位数理解。", "中"),
    },
    "002222": {
        "selection_reason": _selection_reason(
            "符合，因为它虽然不是 InP 主线，但年报已明确产品进入光通信波分复用器与 WSS 链条，属于光学晶体 / 光学元件上游卡位。",
            "公司是全球知名的高功率光隔离器、晶体与精密光学元件厂商，产品被海内外知名激光器和光模块公司广泛采用，说明它更像光学元件 choke point 的候选映射。",
        ),
        "scarcity_view": _scarcity_view("中高", "高功率光隔离器、法拉第器件和 WSS 用衍射光栅都依赖长期工艺积累，但它偏光学元件层，稀缺性仍弱于 InP / EML 这类核心材料。"),
        "capacity_view": _capacity_view("中高", "高端晶体材料扩产仍受晶体生长良率、镀膜工艺、可靠性验证和客户认证约束，不是普通标准件平滑扩产。"),
        "pricing_view": _pricing_view("结构升级", "这层更像高端产品结构改善而非简单现货涨价，议价能力要看 WSS、光隔离器和高端精密光学元件占比提升。"),
        "market_cap_research": _market_cap_research("当前更适合按细分光学晶体与精密光学元件平台理解。", "若光通信占比继续提升，估值锚可从泛激光材料往高端光学器件平台迁移。"),
        "segment_market_view": _segment_market_view("ROADM / WSS 光学器件与高功率光隔离器环节可按数十亿美元级理解，其中 WSS 属于高附加值小而精子环节。", "若按整个光子材料大盘看公司份额仍不高，但在特定晶体与高功率光隔离器细分更接近龙头样本。", "中"),
    },
    "300323": {
        "selection_reason": _selection_reason(
            "符合，因为它已把战略重心拓展到智算中心光互连，并正式启动 Micro LED光模块 的研发与生产，是传统 LED 外延平台里少数切到新路线的 A 股样本。",
            "公司已公开披露首批光通信样品已交付海外客户并持续优化，这让它从普通 LED 周期股，升级成 Micro LED 光互连的早期期权，但层级仍次于 EML / CW / InP 主线。",
        ),
        "scarcity_view": _scarcity_view("中", "若 Micro LED 光互连路线成立，稀缺性会抬升；但当前仍是前瞻验证逻辑，业务纯度和确定性弱于三安光电与云南锗业。"),
        "capacity_view": _capacity_view("中高", "公司拥有全球首条6英寸Micro LED规模化量产线，但从显示量产切到光互连仍要经过样品优化、封装验证和客户导入，不是现成产能直接平移。"),
        "pricing_view": _pricing_view("验证期", "当前更像验证期估值弹性而非实质涨价，只有首批样品从送样走到订单和量产，价格传导才会真正成立。"),
        "market_cap_research": _market_cap_research("当前更适合按 LED 平台叠加 Micro LED 光互连期权理解。", "若海外验证转订单，公司估值锚才有机会从传统 LED 周期切到新光互连平台。"),
        "segment_market_view": _segment_market_view("Micro LED 光互连 / CPO 外置光源仍属早期新路线，可按数十亿美元潜在空间理解，但离规模兑现还有距离。", "公司份额目前更适合按早期样品与潜在份额理解，尚不能按成熟主供应商口径估算。", "早期卡位"),
    },
    "688126": {
        "selection_reason": _selection_reason("符合，因为它是 A 股里最直接的 SOI / 高端硅片映射，Soitec 已验证 Photonics-SOI FY26 超过 1 亿美元。", "最贴近基底 choke point，和 Soitec 的逻辑一致性最高，属于对的层级但仍待利润进一步证明。"),
        "scarcity_view": _scarcity_view("高", "高端 SOI 基底供应少、验证长、切换慢。"),
        "capacity_view": _capacity_view("扩产难", "高端硅片扩产受良率、设备和客户验证共同约束。"),
        "pricing_view": _pricing_view("有涨价基础", "基底层一旦供给偏紧，价格和估值都会更快被抬升。"),
        "market_cap_research": _market_cap_research("当前更适合按 200-400 亿级高端硅片平台理解。", "若高端产品渗透继续提升，可进一步上修。"),
        "segment_market_view": _segment_market_view("Photonics-SOI 已被 Soitec 做到 FY26 超过 1 亿美元收入，国内高端 SOI / 基底环节仍可按百亿美元级长期空间理解。", "公司份额适合按国内关键平台理解。", "高"),
    },
    "605358": {
        "selection_reason": _selection_reason("符合，因为它承接高端硅片平台逻辑，是 SOI 主线的补充映射，12英寸硅片与12英寸硅外延片收入都在快速增长。", "虽然不如沪硅产业直接，但仍站在高端基底层，且在 12 英寸硅片、外延片和超低阻重掺技术上有差异化能力。"),
        "scarcity_view": _scarcity_view("中高", "高端硅片仍有技术门槛，但 SOI 纯度弱于第一主映射。"),
        "capacity_view": _capacity_view("扩产难", "高端硅片扩产受良率、设备与客户导入影响。"),
        "pricing_view": _pricing_view("有涨价基础", "公司已公开表示自 2025 年一季度以来平均出货价格环比逐季提升，高端基底供给收紧时仍有议价空间。"),
        "market_cap_research": _market_cap_research("当前更适合按高端硅片平台理解。", "若高端占比抬升，可上看更高估值。"),
        "segment_market_view": _segment_market_view("高端硅片环节可按百亿美元级理解，其中 12英寸硅片 与 12英寸硅外延片 是更接近高端化的核心子环节。", "公司份额适合按中个位数理解。", "中"),
    },
    "688233": {
        "selection_reason": _selection_reason(
            "符合，因为它更接近存储芯片等离子刻蚀环节的核心耗材，硅零部件已成为第二增长曲线，不再只是泛硅材料映射。",
            "公司是国内少数具备从晶体生长到硅电极成品全链条制造能力的厂商，硅零部件和大直径硅材料都卡在高端刻蚀与存储链条。",
        ),
        "scarcity_view": _scarcity_view("中高", "刻蚀用硅零部件需要高精度、高洁净和一致性验证，公司已进入本土主流存储芯片制造厂及刻蚀设备厂供应链，这层稀缺性强于普通硅材料。"),
        "capacity_view": _capacity_view("中高", "扩产不只是加设备，公司当前募投聚焦12英寸曲面电极、平面电极、导气环等高端刻蚀用硅零部件，8英寸硅片业务仍要等待客户认证后才能拿到批量订单。"),
        "pricing_view": _pricing_view("结构升级", "它更像第二增长曲线带来的产品结构升级和国产替代溢价，而不是简单原材料涨价；真正弹性取决于硅零部件占比继续提升。"),
        "market_cap_research": _market_cap_research("当前更适合按刻蚀耗材 + 高端硅零部件平台理解。", "若本土存储扩产和零部件国产替代继续兑现，估值锚可从材料延伸映射抬到关键耗材平台。"),
        "segment_market_view": _segment_market_view("高端硅材料与刻蚀零部件环节可按数十亿美元级理解，其中中国大陆硅零部件市场 2026 年有望达到约70亿元。", "公司份额适合按低中个位数理解。", "中"),
    },
    "688008": {
        "selection_reason": _selection_reason("符合，因为它是 A 股里最接近连接协议层与 Retimer/CXL 芯片卡位的公司。", "相比线材与连接器，它更接近真正的连接芯片层。"),
        "scarcity_view": _scarcity_view("高", "协议层与连接芯片验证重、壁垒高、客户切换慢。"),
        "capacity_view": _capacity_view("中高", "增长更多取决于设计导入和标准落地，而不是简单扩产线。"),
        "pricing_view": _pricing_view("有涨价基础", "协议层芯片一旦卡位成功，价格弹性强于中游承载件。"),
        "market_cap_research": _market_cap_research("当前更适合按中大市值连接芯片平台理解。", "若 CXL / AEC 商业化提速，可上看更高成长估值。"),
        "segment_market_view": _segment_market_view("连接芯片 / Retimer / CXL 环节可按百亿美元级理解。", "公司份额适合按国内关键平台理解。", "高"),
    },
    "688702": {
        "selection_reason": _selection_reason("符合，因为它是更直接的交换芯片 / fabric 层映射。", "比线缆更接近 AVGO 逻辑，但客户导入仍是核心变量。"),
        "scarcity_view": _scarcity_view("中高", "交换芯片壁垒高，但客户突破仍决定最终稀缺溢价。"),
        "capacity_view": _capacity_view("中高", "受产品迭代和客户平台导入约束，不是简单制造扩产。"),
        "pricing_view": _pricing_view("有涨价基础", "若交换芯片路线成立，价格与估值都更易上修。"),
        "market_cap_research": _market_cap_research("当前更适合按交换芯片候选平台理解。", "若客户导入明确，可向更高平台估值切换。"),
        "segment_market_view": _segment_market_view("AI Ethernet switch / fabric 环节可按百亿美元级理解。", "公司份额适合按早期低份额理解。", "早期卡位"),
    },
    "605277": {
        "selection_reason": _selection_reason("符合，因为它已经进入安费诺链条，是 A 股里少数被全球服务器验证的高速铜缆样本。", "不是连接芯片本体，但商业兑现更清晰。"),
        "scarcity_view": _scarcity_view("中", "高速铜缆连接线壁垒高于普通线缆，但弱于芯片本体。"),
        "capacity_view": _capacity_view("中高", "扩产受海外客户订单与高速规格切换约束。"),
        "pricing_view": _pricing_view("有涨价基础", "高规格铜缆连接线在供需偏紧时具备一定议价能力。"),
        "market_cap_research": _market_cap_research("当前更适合按中小市值高速铜缆供应链样本理解。", "若全球服务器订单持续兑现，可上看更高景气估值。"),
        "segment_market_view": _segment_market_view("高速铜缆 / AEC 连接线环节可按数十亿美元级理解。", "公司份额适合按中个位数理解。", "中"),
    },
    "002130": {
        "selection_reason": _selection_reason("符合，因为它已站上 224G/448G 高速通信线升级主线。", "比普通线材更接近高速铜互连代际升级。"),
        "scarcity_view": _scarcity_view("中", "高速通信线有技术门槛，但稀缺性仍弱于芯片与协议层。"),
        "capacity_view": _capacity_view("中高", "扩产受高规格验证和客户导入约束。"),
        "pricing_view": _pricing_view("有涨价基础", "高规格通信线产品在升级期具备一定溢价。"),
        "market_cap_research": _market_cap_research("当前更适合按高速通信线平台理解。", "若 448G 放量顺利，可上修估值中枢。"),
        "segment_market_view": _segment_market_view("高速通信线环节可按数十亿美元级理解。", "公司份额适合按中个位数理解。", "中"),
    },
    "688515": {
        "selection_reason": _selection_reason("符合，因为它补足高速 PHY / 连接芯片这条支线。", "虽然不如澜起平台化，但更偏单点连接芯片映射。"),
        "scarcity_view": _scarcity_view("中高", "连接芯片壁垒高，但商业兑现还在推进。"),
        "capacity_view": _capacity_view("中高", "真正变量是客户导入和平台认证，不是制造产能本身。"),
        "pricing_view": _pricing_view("待验证", "价格能力要等更明确平台导入。"),
        "market_cap_research": _market_cap_research("当前更适合按成长型连接芯片候选理解。", "若客户突破，估值弹性较大。"),
        "segment_market_view": _segment_market_view("高速 PHY / 连接芯片环节可按数十亿美元级理解。", "公司份额适合按早期低份额理解。", "早期卡位"),
    },
    "688525": {
        "selection_reason": _selection_reason("符合，因为它更接近企业级 SSD 与存储模组产品化兑现层，是 NAND 周期修复最直接的 A 股样本之一。", "它不是 HBM 本体，但企业级存储与产品化能力让它比纯品牌更靠近 AI 存储升级承接层。"),
        "scarcity_view": _scarcity_view("中", "模组与企业级存储有门槛，但稀缺性弱于 HBM、内存接口和先进封装。"),
        "capacity_view": _capacity_view("中高", "扩产取决于企业级产品导入、库存消化和高端产品良率。"),
        "pricing_view": _pricing_view("有涨价基础", "利润改善既受 NAND 重定价影响，也受企业级产品 mix 提升支撑。"),
        "market_cap_research": _market_cap_research("当前更适合按存储产品化平台理解。", "若企业级与高端产品占比提升，可向更高平台估值切换。"),
        "segment_market_view": _segment_market_view("企业级 SSD / 存储模组环节可按数十亿美元级理解。", "公司份额适合按国内重要样本理解。", "中"),
    },
    "001309": {
        "selection_reason": _selection_reason("符合，因为它同时承接控制器与模组，比纯模组更接近存储产品定义权。", "真正的价值在于控制器与产品方案结合，而不是只吃存储现货价格弹性。"),
        "scarcity_view": _scarcity_view("中高", "控制器 + 模组方案壁垒高于纯模组，客户切换也更慢。"),
        "capacity_view": _capacity_view("中高", "扩产要看控制器导入、库存管理和高端客户节奏。"),
        "pricing_view": _pricing_view("有涨价基础", "价格修复叠加控制器方案溢价时，盈利弹性会强于普通模组厂。"),
        "market_cap_research": _market_cap_research("当前更适合按控制器+模组一体化样本理解。", "若高端产品占比提升，可上修估值。"),
        "segment_market_view": _segment_market_view("控制器 / 模组方案环节可按数十亿美元级理解。", "公司份额适合按中个位数理解。", "中"),
    },
    "301308": {
        "selection_reason": _selection_reason("符合，因为它是国内熟知度最高的存储模组与品牌平台之一，但更像景气扩散层而非稀缺 choke point。", "逻辑成立更多来自周期与渠道能力，而不是最上游的供给约束。"),
        "scarcity_view": _scarcity_view("中", "品牌与模组平台有壁垒，但稀缺性弱于 HBM、接口芯片和控制器。"),
        "capacity_view": _capacity_view("中", "扩产更多取决于库存、品牌渠道与客户节奏。"),
        "pricing_view": _pricing_view("有涨价基础", "价格传导主要来自 NAND / DRAM 周期修复和高端产品 mix。"),
        "market_cap_research": _market_cap_research("当前更适合按存储品牌与模组平台理解。", "若 AI 存储需求继续外溢，可看景气重估。"),
        "segment_market_view": _segment_market_view("存储模组 / 品牌环节可按数十亿美元级理解。", "公司份额适合按国内龙头理解。", "中"),
    },
    "603986": {
        "selection_reason": _selection_reason("符合，因为它不只是泛存储景气映射，2025 年已公开披露利基 DRAM 与 SLC NAND 出现量价齐升。", "它卡的不是 HBM 本体，而是利基 DRAM 与 SLC NAND 这类设计层的结构性修复，是 memory cycle 向设计侧传导的直接样本。"),
        "scarcity_view": _scarcity_view("中高", "利基 DRAM 与 SLC NAND 供应商不多，设计与产品定义能力强于纯模组。"),
        "capacity_view": _capacity_view("中高", "扩产取决于 wafer 供给、设计迭代和高端客户导入，而不是简单堆库存。"),
        "pricing_view": _pricing_view("有涨价基础", "公司已公开验证利基 DRAM 与 SLC NAND 量价齐升，利润弹性来自价格修复叠加产品结构升级。"),
        "market_cap_research": _market_cap_research("当前更适合按利基存储设计平台理解。", "若 memory cycle 与 AI 存储需求共振，可继续上修估值。"),
        "segment_market_view": _segment_market_view("利基 DRAM / SLC NAND / 存储设计环节可按数十亿美元级理解。", "公司份额适合按国内重要设计样本理解。", "中"),
    },
    "603019": {
        "selection_reason": _selection_reason("符合，因为它更接近供给侧算力平台，而不是普通服务器整机，核心是把 GPU 真正上电交付。", "相比单纯卖硬件，中科曙光更卡在 GPU 真正上电交付、资源调度、算力基础设施和平台承接层。"),
        "scarcity_view": _scarcity_view("中高", "资源调度、平台能力和算力基础设施协同，壁垒高于单点服务器交付。"),
        "capacity_view": _capacity_view("扩产难", "扩容要看机房、GPU、网络与上电节奏配合，不是签约之后自然兑现。"),
        "pricing_view": _pricing_view("结构升级", "利润改善更多来自平台化交付和高附加值算力服务，而不只是硬件涨价。"),
        "market_cap_research": _market_cap_research("当前更适合按大市值算力平台理解。", "若 GPU 云与平台资源层持续强化，估值锚可继续抬升。"),
        "segment_market_view": _segment_market_view("AI 算力基础设施 / 资源调度平台可按数十亿美元到百亿美元级理解。", "公司份额适合按国内平台型核心样本理解。", "中高"),
    },
    "300738": {
        "selection_reason": _selection_reason("符合，因为它承接的是通电机房与机柜资源，而这正是 GPU 云真正落地前的硬约束。", "比起讲 GPU 数量，奥飞数据更贴近 MW 上电和机柜交付这层现实瓶颈。"),
        "scarcity_view": _scarcity_view("中高", "通电机房、机柜资源和园区电力配套在当前比普通 IDC 空置面积更稀缺。"),
        "capacity_view": _capacity_view("中高", "关键变量是机房上电节奏和电力配套，不是单纯签约面积增长。"),
        "pricing_view": _pricing_view("有涨价基础", "在供给偏紧区域，机柜与上架资源更容易体现租赁价格和附加服务溢价。"),
        "market_cap_research": _market_cap_research("当前更适合按电力约束下的 IDC 资源票理解。", "若 MW 上电与租用率继续提升，可抬升估值。"),
        "segment_market_view": _segment_market_view("IDC / 机柜资源 / 上电配套环节可按数十亿美元级理解。", "公司份额适合按区域重要样本理解。", "中"),
    },
    "000977": {
        "selection_reason": _selection_reason("符合，因为它是 AI 服务器部署最直接的国内样本之一，但层级更偏部署而非最稀缺资源层。", "真正要看的不是出货热度，而是液冷、系统集成和 AI 全栈交付能力。"),
        "scarcity_view": _scarcity_view("中", "整机集成有壁垒，但稀缺性弱于上电资源、GPU 获取和平台调度。"),
        "capacity_view": _capacity_view("中高", "扩产取决于客户订单、液冷方案与供应链协同。"),
        "pricing_view": _pricing_view("结构升级", "利润改善更多来自液冷和高端 AI 系统占比提升，而不只是整机涨价。"),
        "market_cap_research": _market_cap_research("当前更适合按 AI 服务器龙头理解。", "若系统化交付持续强化，可维持高景气估值。"),
        "segment_market_view": _segment_market_view("AI 服务器整机与系统集成可按百亿美元级理解。", "公司份额适合按国内高份额理解。", "高"),
    },
    "300383": {
        "selection_reason": _selection_reason("符合，因为它承接云基础设施与 IDC 运营，是算力云扩散链的资源型样本。", "方向成立，但更偏受益层，纯度弱于真正供给侧算力平台。"),
        "scarcity_view": _scarcity_view("中", "云基础设施有资源门槛，但平台稀缺性弱于 GPU 与上电资源本身。"),
        "capacity_view": _capacity_view("中", "扩产主要受资本开支、机房建设和利用率影响。"),
        "pricing_view": _pricing_view("有涨价基础", "若区域算力资源偏紧，租赁与云服务价格仍有支撑。"),
        "market_cap_research": _market_cap_research("当前更适合按 IDC / 云基础设施扩散样本理解。", "若算力需求持续外溢，可看补涨。"),
        "segment_market_view": _segment_market_view("IDC / 云基础设施环节可按数十亿美元级理解。", "公司份额适合按区域样本理解。", "中"),
    },
    "688981": {
        "selection_reason": _selection_reason("符合，因为它是 A 股里最直接的先进逻辑代工平台映射，更接近 AI 半导体 foundry 中枢。", "真正的变量不是概念热度，而是先进逻辑、成熟节点与产能利用率 95.8% 共同验证的平台承接能力。"),
        "scarcity_view": _scarcity_view("高", "先进逻辑代工需要长期工艺积累、客户认证和极高资本开支，是典型平台型稀缺层。"),
        "capacity_view": _capacity_view("扩产难", "扩产既要解决设备与资本开支，也要解决良率与产能利用率 95.8% 背后的产品 mix 和客户导入。"),
        "pricing_view": _pricing_view("有涨价基础", "代工平台的价格和利润更多来自高附加值节点与利用率维持，而不只是 wafer 数增加。"),
        "market_cap_research": _market_cap_research("当前更适合按大陆先进代工平台理解。", "若先进逻辑与高端客户占比继续提升，可上修估值。"),
        "segment_market_view": _segment_market_view("先进逻辑代工环节可按百亿美元级理解。", "公司份额适合按大陆核心平台理解。", "高"),
    },
    "688347": {
        "selection_reason": _selection_reason("符合，因为它比泛晶圆制造更贴近特色工艺和功率器件代工，是 specialty foundry 的自然主映射。", "功率器件、模拟、电源管理等特色工艺才是和 Tower / X-Fab 更接近的层级。"),
        "scarcity_view": _scarcity_view("中高", "特色工艺的稀缺性来自功率器件、模拟和长期客户认证，而不是最先进节点 headline。"),
        "capacity_view": _capacity_view("中高", "公司 2025 年产能利用率 106.1%，说明特色工艺供给处在高位运行，扩产和导入都不轻松。"),
        "pricing_view": _pricing_view("结构升级", "利润改善更依赖高附加值特色工艺占比，而不是简单 wafer 涨价。"),
        "market_cap_research": _market_cap_research("当前更适合按特色工艺平台理解。", "若功率器件与高端特色工艺占比提升，可继续上修估值。"),
        "segment_market_view": _segment_market_view("功率器件 / 模拟 / PMIC / specialty foundry 可按数十亿美元到百亿美元级理解。", "公司份额适合按国内关键特色工艺平台理解。", "中高"),
    },
    "688396": {
        "selection_reason": _selection_reason("符合，因为它是功率 / IDM 平台补充映射，更接近 AI 电力链和成熟工艺承接层。", "虽然不如纯 foundry 直接，但功率器件与 IDM 平台能力让它处在特色工艺生态的重要位置。"),
        "scarcity_view": _scarcity_view("中", "IDM 功率平台有壁垒，但纯度弱于 foundry 本体。"),
        "capacity_view": _capacity_view("中高", "扩容受功率器件产品 mix、客户验证和资本开支约束。"),
        "pricing_view": _pricing_view("结构升级", "利润改善更多来自高端功率器件和工业/车规 mix。"),
        "market_cap_research": _market_cap_research("当前更适合按功率半导体平台理解。", "若 AI 电力化继续推进，可抬升估值。"),
        "segment_market_view": _segment_market_view("功率器件 / IDM 平台环节可按数十亿美元级理解。", "公司份额适合按国内重要平台理解。", "中"),
    },
    "688249": {
        "selection_reason": _selection_reason("符合，因为它是代工平台的补充映射，但更偏成熟制程与特定客户承接。", "与中芯国际相比，它更像补充平台，不是 foundry 最核心 choke point。"),
        "scarcity_view": _scarcity_view("中", "晶圆代工有门槛，但平台性与客户深度弱于第一主映射。"),
        "capacity_view": _capacity_view("中", "扩产更多受成熟制程客户结构和利用率影响。"),
        "pricing_view": _pricing_view("结构升级", "高附加值产品 mix 提升时，盈利改善会强于单纯出货恢复。"),
        "market_cap_research": _market_cap_research("当前更适合按补充代工平台理解。", "若客户结构改善，可看阶段性重估。"),
        "segment_market_view": _segment_market_view("成熟制程 / 代工平台环节可按数十亿美元级理解。", "公司份额适合按中低个位数理解。", "中"),
    },
    "688120": {
        "selection_reason": _selection_reason("符合，因为它卡在先进封装关键设备里的 CMP / 平坦化工艺，这不是普通前道设备外溢。", "先进封装要走向 CoWoS / HBM，平坦化是必须解决的基础环节，所以它更像设备 choke point。"),
        "scarcity_view": _scarcity_view("中高", "CMP 与先进封装平坦化工艺壁垒高，客户验证慢，良率要求高。"),
        "capacity_view": _capacity_view("扩产难", "设备放量取决于客户 capex、验证节奏和先进封装导入速度，不是设备厂自己想扩就能扩。"),
        "pricing_view": _pricing_view("有涨价基础", "当 CoWoS / HBM 产能紧张时，关键设备通常具备更强的溢价与毛利稳定性。"),
        "market_cap_research": _market_cap_research("当前更适合按先进封装关键设备平台理解。", "若先进封装设备渗透继续提升，可上修估值。"),
        "segment_market_view": _segment_market_view("CoWoS / HBM / 先进封装平坦化设备环节可按数十亿美元级理解。", "公司份额适合按国内关键设备样本理解。", "中高"),
    },
    "300604": {
        "selection_reason": _selection_reason("符合，因为它更接近先进测试和封测装备，是先进封装从 wafer 走向可交付芯片的关键后段环节。", "真正的难点在先进测试、良率和客户验证，而不只是泛设备扩产。"),
        "scarcity_view": _scarcity_view("中高", "先进测试设备与良率工程要求高，客户验证周期长。"),
        "capacity_view": _capacity_view("中高", "扩容要看测试设备产能、先进封测客户资本开支和验证速度。"),
        "pricing_view": _pricing_view("有涨价基础", "在先进封装升级期，先进测试设备与服务通常比传统后段更有溢价。"),
        "market_cap_research": _market_cap_research("当前更适合按先进测试设备平台理解。", "若先进封装占比持续提升，可抬升估值。"),
        "segment_market_view": _segment_market_view("先进测试 / 封装后段设备可按数十亿美元级理解。", "公司份额适合按国内重要平台理解。", "中"),
    },
    "600520": {
        "selection_reason": _selection_reason("符合，因为它是封测平台补充映射，但层级次于关键设备和先进测试。", "更多是受益于封装升级和客户扩产，而不是最硬的设备 choke point。"),
        "scarcity_view": _scarcity_view("中", "封测平台有壁垒，但稀缺性弱于关键设备与最先进封装工艺。"),
        "capacity_view": _capacity_view("中高", "扩产受客户订单和先进封测占比影响。"),
        "pricing_view": _pricing_view("结构升级", "利润改善主要来自先进封测占比提升。"),
        "market_cap_research": _market_cap_research("当前更适合按封测平台补充映射理解。", "若先进封装需求外溢，可看阶段性重估。"),
        "segment_market_view": _segment_market_view("封测平台环节可按数十亿美元级理解。", "公司份额适合按中个位数理解。", "中"),
    },
    "603773": {
        "selection_reason": _selection_reason("符合，因为它押的是玻璃基板材料路线，是先进封装里更前瞻的新材料期权。", "它不是当下最确定的放量层，但一旦路线验证，材料卡位会快速重估。"),
        "scarcity_view": _scarcity_view("中高", "玻璃基板材料和工艺 know-how 稀缺，但目前仍处早期导入。"),
        "capacity_view": _capacity_view("扩产难", "路线导入要经过材料、制程和客户共研验证。"),
        "pricing_view": _pricing_view("验证期", "当前更偏路线期权，价格传导要等量产验证。"),
        "market_cap_research": _market_cap_research("当前更适合按玻璃基板前瞻材料样本理解。", "若客户验证顺利，可显著抬升估值。"),
        "segment_market_view": _segment_market_view("玻璃基板材料环节可按数十亿美元潜在空间理解。", "公司份额适合按早期潜在份额理解。", "早期卡位"),
    },
    "601208": {
        "selection_reason": _selection_reason("符合，因为它承接玻璃基板相关加工与材料链，是新路线的次级映射。", "方向相关，但纯度次于核心材料和工艺设备。"),
        "scarcity_view": _scarcity_view("中", "有工艺门槛，但最终稀缺性要看玻璃基板路线是否大规模落地。"),
        "capacity_view": _capacity_view("中高", "扩产要跟着客户验证和材料路线推进。"),
        "pricing_view": _pricing_view("验证期", "当前更偏路线弹性，价格能力仍待量产验证。"),
        "market_cap_research": _market_cap_research("当前更适合按新材料补充映射理解。", "若玻璃基板导入提速，可看重估。"),
        "segment_market_view": _segment_market_view("玻璃基板相关材料与加工环节可按数十亿美元潜在空间理解。", "公司份额适合按早期样本理解。", "早期卡位"),
    },
    "002106": {
        "selection_reason": _selection_reason("符合，因为它承接封装材料和先进封装扩散逻辑，是玻璃基板路线的外围样本。", "比核心工艺设备更外层，但仍可观察路线传导。"),
        "scarcity_view": _scarcity_view("中", "材料端有门槛，但稀缺性弱于关键设备与核心新材料。"),
        "capacity_view": _capacity_view("中", "扩产主要取决于封装景气和新材料导入节奏。"),
        "pricing_view": _pricing_view("结构升级", "利润改善更依赖高附加值材料占比提升。"),
        "market_cap_research": _market_cap_research("当前更适合按封装材料扩散样本理解。", "若高端材料占比上升，可看补涨。"),
        "segment_market_view": _segment_market_view("封装材料环节可按数十亿美元级理解。", "公司份额适合按中个位数理解。", "中"),
    },
    "600118": {
        "selection_reason": _selection_reason("符合，因为它是 A 股里最接近商业航天系统级平台的样本，年报已披露全年成功发射 24颗 小微小卫星。", "系统级能力比单一部件更接近 Rocket Lab / SpaceX 的层级，是商业航天主线里更硬的映射。"),
        "scarcity_view": _scarcity_view("高", "卫星总装、系统级交付和整星工程能力在 A 股里都很稀缺。"),
        "capacity_view": _capacity_view("中高", "扩容取决于卫星组网节奏、整星交付能力和任务排期。"),
        "pricing_view": _pricing_view("结构升级", "利润改善更多来自系统级任务和商业航天订单占比提升。"),
        "market_cap_research": _market_cap_research("当前更适合按卫星系统平台理解。", "若低轨组网持续提速，可上修估值。"),
        "segment_market_view": _segment_market_view("卫星系统平台 / 商业航天制造环节可按数十亿美元级理解。", "公司份额适合按国内系统级核心样本理解。", "高"),
    },
    "600879": {
        "selection_reason": _selection_reason("符合，因为它承接商业航天高端部件与军民融合系统，是系统平台外的重要配套层。", "它不像总装平台那样直接，但更接近高价值量核心部件。"),
        "scarcity_view": _scarcity_view("中高", "高端航天部件与系统配套有门槛，但层级次于总装平台。"),
        "capacity_view": _capacity_view("中高", "扩容取决于任务节奏和客户订单验证。"),
        "pricing_view": _pricing_view("有涨价基础", "高价值量部件在任务密集期具备一定溢价。"),
        "market_cap_research": _market_cap_research("当前更适合按航天高端配套平台理解。", "若商业航天订单占比抬升，可看重估。"),
        "segment_market_view": _segment_market_view("航天高端部件 / 系统配套环节可按数十亿美元级理解。", "公司份额适合按国内重要配套样本理解。", "中"),
    },
    "300762": {
        "selection_reason": _selection_reason("符合，因为它不是泛卫星概念，而是已披露千帆星座/G60 低轨相关业务和卫星通信分系统供应关系的直接样本。", "公司已披露千帆星座相关产品和 3.11亿元 已签未完合同，说明它更靠近组网建设节奏而非主题情绪。"),
        "scarcity_view": _scarcity_view("中高", "信关站、低轨通信分系统和卫星通信载荷在当前组网期稀缺性强于普通应用层。"),
        "capacity_view": _capacity_view("中高", "扩容要看星座建设节奏、已签未完合同兑现和地面段建设进度。"),
        "pricing_view": _pricing_view("有涨价基础", "在组网建设高峰期，核心通信分系统更容易维持较好毛利。"),
        "market_cap_research": _market_cap_research("当前更适合按低轨卫星通信分系统样本理解。", "若千帆星座持续推进，可上修估值。"),
        "segment_market_view": _segment_market_view("低轨卫星通信分系统 / 信关站环节可按数十亿美元级理解。", "公司份额适合按早期但直接受益样本理解。", "中"),
    },
    "600406": {
        "selection_reason": _selection_reason("符合，因为它最接近电网升级中枢和调度自动化，是 AI 用电约束在 A 股里最硬的映射之一。", "AI power bottleneck 要先看调度自动化和电网系统层，而不是泛公用事业；公司 2025H1 新签合同已达 354.32 亿元。"),
        "scarcity_view": _scarcity_view("高", "调度自动化、电网控制系统和新型电力系统中枢能力在国内替代难度高。"),
        "capacity_view": _capacity_view("中高", "354.32 亿元 新签合同说明景气已兑现，但交付节奏仍受电网投资和项目排产约束。"),
        "pricing_view": _pricing_view("有涨价基础", "电网设备景气上行时，系统解决方案和高附加值设备更容易维持价格与毛利。"),
        "market_cap_research": _market_cap_research("当前更适合按电网自动化中枢平台理解。", "若 AI 用电推动电网 capex 持续上修，可进一步抬升估值。"),
        "segment_market_view": _segment_market_view("电网自动化 / 调度系统 / 新型电力系统可按数十亿美元到百亿美元级理解。", "公司份额适合按国内高份额核心平台理解。", "高"),
    },
    "000400": {
        "selection_reason": _selection_reason("符合，因为它更接近输配电关键设备，是电网升级最直接的硬件承接层。", "与单纯公用事业股不同，它卖的是输配电关键设备和系统，直接受益于 AI 扩容下的电网 capex。"),
        "scarcity_view": _scarcity_view("中高", "高压输配电设备和关键电气系统供应商少、验证重。"),
        "capacity_view": _capacity_view("中高", "扩产取决于设备交期、订单结构和电网投资节奏。"),
        "pricing_view": _pricing_view("有涨价基础", "在设备供需偏紧时，高压电气设备具备较强议价基础。"),
        "market_cap_research": _market_cap_research("当前更适合按输配电设备平台理解。", "若电网投资周期持续，可抬升估值。"),
        "segment_market_view": _segment_market_view("输配电关键设备环节可按数十亿美元级理解。", "公司份额适合按国内重要设备平台理解。", "中高"),
    },
    "601179": {
        "selection_reason": _selection_reason("符合，因为它承接输变电设备，是电力扩容中最受益的硬件链之一。", "方向正确，但更偏广谱设备，纯度次于调度与系统中枢。"),
        "scarcity_view": _scarcity_view("中", "输变电设备有门槛，但平台属性弱于电网自动化中枢。"),
        "capacity_view": _capacity_view("中高", "扩产主要受订单交付和电网投资节奏影响。"),
        "pricing_view": _pricing_view("有涨价基础", "若设备交期收紧，输变电设备仍有价格支撑。"),
        "market_cap_research": _market_cap_research("当前更适合按输变电设备扩散样本理解。", "若订单结构继续改善，可阶段性重估。"),
        "segment_market_view": _segment_market_view("输变电设备环节可按数十亿美元级理解。", "公司份额适合按中个位数到高个位数理解。", "中"),
    },
    "300693": {
        "selection_reason": _selection_reason("符合，因为它更接近电力设备和配套扩散链，是 AI 电力化的次级受益样本。", "方向成立，但层级弱于电网自动化和高压设备核心环节。"),
        "scarcity_view": _scarcity_view("中", "配套设备有门槛，但稀缺性弱于主设备。"),
        "capacity_view": _capacity_view("中", "扩产更多看订单和配套节奏。"),
        "pricing_view": _pricing_view("结构升级", "利润改善更依赖高端配套占比提升。"),
        "market_cap_research": _market_cap_research("当前更适合按电力配套扩散样本理解。", "若 AI 电力链持续外溢，可看补涨。"),
        "segment_market_view": _segment_market_view("电力配套设备环节可按数十亿美元级理解。", "公司份额适合按中低个位数理解。", "中"),
    },
    "600111": {
        "selection_reason": _selection_reason("符合，因为它不只是泛稀土股，2024 年冶炼分离指标已达 170,001吨，占全国 66.93%，是真正的战略材料 choke point。", "关键不只是资源量，而是占全国 66.93% 的冶炼分离、磁材延链和总量控制，这层才是关键矿物最难替代的地方。"),
        "scarcity_view": _scarcity_view("高", "稀土冶炼分离、指标配额和磁材延链能力共同构成真正稀缺层。"),
        "capacity_view": _capacity_view("扩产难", "扩容不只看矿，还要看冶炼分离指标、政策和下游磁材承接。"),
        "pricing_view": _pricing_view("有涨价基础", "战略属性、配额与价格重估共振时，冶炼分离环节比下游更容易体现定价权。"),
        "market_cap_research": _market_cap_research("当前更适合按战略稀土平台理解。", "若磁材与战略材料属性继续强化，可上修估值。"),
        "segment_market_view": _segment_market_view("稀土冶炼分离 / 磁材延链环节可按数十亿美元级理解。", "公司份额适合按国内绝对主导平台理解。", "高"),
    },
    "600392": {
        "selection_reason": _selection_reason("符合，因为它是资源 + 加工一体化样本，更接近供应链自主可控而不是单纯资源价格弹性。", "与只卖资源不同，一体化加工能力让它更贴近关键矿物真正的价值捕获层。"),
        "scarcity_view": _scarcity_view("中高", "资源与加工一体化比单纯资源更稀缺，但政策和价格仍是关键变量。"),
        "capacity_view": _capacity_view("中高", "扩产要看资源供给、加工能力和下游需求同步。"),
        "pricing_view": _pricing_view("有涨价基础", "资源价格上行叠加工能力时，盈利弹性更强。"),
        "market_cap_research": _market_cap_research("当前更适合按资源+加工一体化平台理解。", "若战略材料属性被继续重估，可上修估值。"),
        "segment_market_view": _segment_market_view("稀土资源 + 加工一体化环节可按数十亿美元级理解。", "公司份额适合按国内重要平台理解。", "中"),
    },
    "600259": {
        "selection_reason": _selection_reason("符合，因为它承接战略资源逻辑，是关键矿物链的补充映射。", "方向相关，但相较稀土冶炼分离和深加工平台，层级略靠后。"),
        "scarcity_view": _scarcity_view("中", "资源属性有价值，但加工与系统地位弱于核心主映射。"),
        "capacity_view": _capacity_view("中", "扩产主要看资源项目推进和价格环境。"),
        "pricing_view": _pricing_view("有涨价基础", "战略资源价格上行时具备弹性。"),
        "market_cap_research": _market_cap_research("当前更适合按战略资源补充样本理解。", "若关键矿物价格继续走强，可阶段性重估。"),
        "segment_market_view": _segment_market_view("战略资源环节可按数十亿美元级理解。", "公司份额适合按中低个位数理解。", "中"),
    },
    "301413": {
        "selection_reason": _selection_reason("符合，因为它更接近机器人手部 / 力控 sensing 所需的高精度传感器，而不是泛机器人整机叙事。", "真正有价值的是高精度传感器在力控闭环和复杂操作里的数据质量，这一层比普通结构件更接近 VPG 的 precision sensing 映射。"),
        "scarcity_view": _scarcity_view("中高", "高精度传感器进入机器人手部和力控闭环后，验证周期长、切换慢，稀缺性强于普通电子零部件。"),
        "capacity_view": _capacity_view("中高", "扩量既要看精度一致性和良率，也要看机器人客户导入与量产节奏。"),
        "pricing_view": _pricing_view("有涨价基础", "高附加值 sensing 器件更依赖性能与可靠性溢价，价格压力通常小于标准化部件。"),
        "market_cap_research": _market_cap_research("当前更适合按机器人高精度传感器样本理解。", "若手部 / 力控 sensing 订单持续兑现，可继续上修估值。"),
        "segment_market_view": _segment_market_view("高精度传感器 / 力控 / 机器人感知环节可按数十亿美元级理解。", "公司份额更适合按细分国产化样本理解。", "中"),
    },
    "300124": {
        "selection_reason": _selection_reason("符合，因为它是平台型工业自动化样本，具备人形机器人零部件延展能力。", "纯度弱于谐波减速器和关节控制主线，但平台能力让它适合做高确定性观察样本。"),
        "scarcity_view": _scarcity_view("中", "平台能力强，但机器人业务纯度一般。"),
        "capacity_view": _capacity_view("中高", "扩量主要受客户送样、零部件导入和工业自动化景气影响。"),
        "pricing_view": _pricing_view("结构升级", "利润改善更多来自高附加值机器人零部件占比提升。"),
        "market_cap_research": _market_cap_research("当前更适合按平台型自动化龙头理解。", "若机器人零部件订单持续突破，可看重估。"),
        "segment_market_view": _segment_market_view("机器人驱动 / 自动化平台环节可按数十亿美元级理解。", "公司份额适合按平台样本理解。", "中"),
    },
    "603728": {
        "selection_reason": _selection_reason("符合，因为它承接减速器与执行环节，是机器人主线的次级映射。", "方向正确，但稀缺性和验证强度弱于谐波减速器第一主映射。"),
        "scarcity_view": _scarcity_view("中", "执行部件有门槛，但层级次于真正卡住自由度和精度的核心件。"),
        "capacity_view": _capacity_view("中", "扩量主要看客户验证和机器人放量节奏。"),
        "pricing_view": _pricing_view("结构升级", "利润改善更依赖机器人收入占比抬升。"),
        "market_cap_research": _market_cap_research("当前更适合按机器人执行件候选理解。", "若客户突破，可看阶段性重估。"),
        "segment_market_view": _segment_market_view("机器人执行部件环节可按数十亿美元级理解。", "公司份额适合按中低个位数理解。", "中"),
    },
    "688160": {
        "selection_reason": _selection_reason("符合，因为它不是泛机器人概念，公司已公开披露 2025 年机器人行业收入 3.71 亿元，并形成旋转关节平台方案。", "真正有价值的是控制器、驱控一体和旋转关节平台方案，这比普通零件更接近人形机器人核心控制层。"),
        "scarcity_view": _scarcity_view("中高", "控制器、驱控和关节平台验证重，替代难度高于普通结构件。"),
        "capacity_view": _capacity_view("中高", "扩容取决于旋转关节平台方案导入和机器人收入持续放量。"),
        "pricing_view": _pricing_view("有涨价基础", "高附加值驱控方案更依赖功能和系统性能，具备一定溢价。"),
        "market_cap_research": _market_cap_research("当前更适合按机器人驱控与关节平台理解。", "若机器人业务继续高增，可上修估值。"),
        "segment_market_view": _segment_market_view("机器人控制器 / 驱控一体 / 关节平台环节可按数十亿美元级理解。", "公司份额适合按细分高成长样本理解。", "中"),
    },
    "301421": {
        "selection_reason": _selection_reason("符合，因为它承接精密执行和机器人部件，是感知/执行链条的补充映射。", "方向相关，但层级弱于谐波减速器和驱控系统。"),
        "scarcity_view": _scarcity_view("中", "精密执行件有门槛，但稀缺性次于主 choke point。"),
        "capacity_view": _capacity_view("中", "扩量主要看客户验证和量产节奏。"),
        "pricing_view": _pricing_view("结构升级", "利润改善更依赖机器人相关收入占比提升。"),
        "market_cap_research": _market_cap_research("当前更适合按机器人精密部件候选理解。", "若订单验证继续推进，可看重估。"),
        "segment_market_view": _segment_market_view("机器人精密部件环节可按数十亿美元级理解。", "公司份额适合按早期样本理解。", "中"),
    },
    "688307": {
        "selection_reason": _selection_reason("符合，因为它站在传感和控制交叉层，是机器人感知升级的补充样本。", "方向对，但纯度和证据强度弱于主传感和执行件。"),
        "scarcity_view": _scarcity_view("中", "传感/控制有门槛，但仍处主题扩散层。"),
        "capacity_view": _capacity_view("中", "扩量主要看客户导入。"),
        "pricing_view": _pricing_view("待验证", "价格能力仍需更多量产验证。"),
        "market_cap_research": _market_cap_research("当前更适合按机器人感知候选理解。", "若客户突破，可看弹性。"),
        "segment_market_view": _segment_market_view("机器人感知补充环节可按数十亿美元级理解。", "公司份额适合按低个位数理解。", "中"),
    },
    "688002": {
        "selection_reason": _selection_reason("符合，因为它承接机器人感知 / 视觉补充链条，是视觉侧的观察样本。", "方向成立，但与主 choke point 的一致性弱于减速器、驱控和核心传感器。"),
        "scarcity_view": _scarcity_view("中", "视觉链有技术门槛，但市场参与者更多。"),
        "capacity_view": _capacity_view("中", "扩量主要取决于客户验证和场景落地。"),
        "pricing_view": _pricing_view("待验证", "价格能力需等更明确商业化验证。"),
        "market_cap_research": _market_cap_research("当前更适合按机器人视觉观察样本理解。", "若感知路线放量，可看弹性。"),
        "segment_market_view": _segment_market_view("机器人视觉 / 感知补充环节可按数十亿美元级理解。", "公司份额适合按低个位数理解。", "中"),
    },
    "688333": {
        "selection_reason": _selection_reason("符合，因为它承接机器人结构件与轻量化制造，是 SSYS 逻辑在 A 股的更直接制造映射。", "不是最稀缺的控制或执行件，但在结构件验证初期有现实承接价值。"),
        "scarcity_view": _scarcity_view("中", "结构件工艺有壁垒，但稀缺性弱于传动和传感。"),
        "capacity_view": _capacity_view("中高", "扩量主要看结构件订单、材料方案和认证节奏。"),
        "pricing_view": _pricing_view("结构升级", "利润改善更依赖高附加值结构件和制造方案占比。"),
        "market_cap_research": _market_cap_research("当前更适合按机器人结构件平台理解。", "若量产验证继续推进，可重估。"),
        "segment_market_view": _segment_market_view("机器人结构件 / 轻量化制造环节可按数十亿美元级理解。", "公司份额适合按国内重要样本理解。", "中"),
    },
    "300580": {
        "selection_reason": _selection_reason("符合，因为它承接 3D 打印与制造平台，是结构件路线的补充映射。", "方向对，但层级次于被验证过的核心结构件供应商。"),
        "scarcity_view": _scarcity_view("中", "3D 打印工艺有门槛，但商业兑现仍需更多量产订单。"),
        "capacity_view": _capacity_view("中", "扩量主要看材料和客户认证。"),
        "pricing_view": _pricing_view("结构升级", "利润改善取决于工业级高附加值产品占比提升。"),
        "market_cap_research": _market_cap_research("当前更适合按制造平台补充样本理解。", "若机器人结构件占比提升，可看重估。"),
        "segment_market_view": _segment_market_view("3D 打印 / 结构制造环节可按数十亿美元级理解。", "公司份额适合按中低个位数理解。", "中"),
    },
    "002747": {
        "selection_reason": _selection_reason("符合，因为它承接骨架与结构件逻辑，是机器人轻量化路线的扩散样本。", "更像扩散受益层，而不是最核心卡点。"),
        "scarcity_view": _scarcity_view("中", "结构件有工艺门槛，但稀缺性有限。"),
        "capacity_view": _capacity_view("中", "扩量主要看客户导入和量产节奏。"),
        "pricing_view": _pricing_view("结构升级", "利润改善来自结构件占比抬升。"),
        "market_cap_research": _market_cap_research("当前更适合按机器人结构件扩散样本理解。", "若订单突破，可看弹性。"),
        "segment_market_view": _segment_market_view("机器人结构件环节可按数十亿美元级理解。", "公司份额适合按低个位数理解。", "中"),
    },
    "603667": {
        "selection_reason": _selection_reason("符合，因为它承接精密制造与材料工艺，是机器人制造侧的补充映射。", "方向相关，但离真正主 choke point 更远。"),
        "scarcity_view": _scarcity_view("中", "工艺有门槛，但稀缺性有限。"),
        "capacity_view": _capacity_view("中", "扩量要看机器人客户和材料方案导入。"),
        "pricing_view": _pricing_view("结构升级", "利润改善更多依赖高端制造占比提升。"),
        "market_cap_research": _market_cap_research("当前更适合按精密制造补充样本理解。", "若机器人相关业务突破，可看重估。"),
        "segment_market_view": _segment_market_view("机器人制造补充环节可按数十亿美元级理解。", "公司份额适合按低个位数理解。", "中"),
    },
    "688027": {
        "selection_reason": _selection_reason("符合，因为它是 A 股里最接近量子硬件系统层的标的，2025 年量子计算业务收入约 1.20 亿元，并已实现两台量子计算整机交付。", "量子真正稀缺的不是概念合作，而是两台量子计算整机交付背后的量子整机、稀释制冷机和测控系统一起推进市场化，这家公司最贴近这一层。"),
        "scarcity_view": _scarcity_view("高", "量子系统、测控和制冷工程化供应商极少，验证周期长。"),
        "capacity_view": _capacity_view("扩产难", "量子硬件仍是高单价、小批量、工程化交付，扩容速度远慢于市场热度。"),
        "pricing_view": _pricing_view("验证期", "当前仍以科研装备和项目制交付为主，真正价格传导取决于系统持续商业化。"),
        "market_cap_research": _market_cap_research("当前更适合按量子硬件系统锚点理解。", "若整机、稀释制冷机和测控系统持续放量，可显著抬升估值。"),
        "segment_market_view": _segment_market_view("量子硬件系统 / 测控 / 稀释制冷机可按数十亿美元早期市场理解。", "公司份额适合按国内核心平台理解。", "高"),
    },
    "002158": {
        "selection_reason": _selection_reason("符合，因为它承接量子通信和量子科技外围平台，是量子主线的补充样本。", "方向对，但层级弱于真正的量子硬件与系统工程。"),
        "scarcity_view": _scarcity_view("中", "有技术门槛，但纯度弱于硬件系统层。"),
        "capacity_view": _capacity_view("中", "扩量取决于项目落地。"),
        "pricing_view": _pricing_view("待验证", "价格能力仍需更多商业化证明。"),
        "market_cap_research": _market_cap_research("当前更适合按量子外围平台理解。", "若订单推进，可看弹性。"),
        "segment_market_view": _segment_market_view("量子外围平台环节可按数十亿美元早期空间理解。", "公司份额适合按补充样本理解。", "中"),
    },
    "688012": {
        "selection_reason": _selection_reason("符合，因为它更接近前段制造设备，是量子器件要走向工程化时绕不开的卖铲人层。", "ALRIB 逻辑本质上是 MBE 与前段制造设备，而中微公司最接近国内高端前段制造设备映射。"),
        "scarcity_view": _scarcity_view("高", "前段制造设备、真空和高精度工艺控制供应商少，客户验证极重。"),
        "capacity_view": _capacity_view("扩产难", "设备放量要看研发迭代、客户验证和高端制造导入。"),
        "pricing_view": _pricing_view("有涨价基础", "高端前段设备一旦进入科研和工程化产线，通常具备较强溢价。"),
        "market_cap_research": _market_cap_research("当前更适合按前段制造设备平台理解。", "若量子器件前段设备需求持续强化，可上修估值。"),
        "segment_market_view": _segment_market_view("MBE / 前段制造设备环节可按数十亿美元级理解。", "公司份额适合按国内高端设备平台理解。", "中高"),
    },
    "300316": {
        "selection_reason": _selection_reason("符合，因为它承接真空与精密设备，是量子工程化链条的次级卖铲人样本。", "方向相关，但纯度次于前段核心设备。"),
        "scarcity_view": _scarcity_view("中", "真空设备有门槛，但与量子主线的一致性次于核心前段设备。"),
        "capacity_view": _capacity_view("中高", "扩量主要看科研设备与客户导入。"),
        "pricing_view": _pricing_view("有涨价基础", "高端科研与精密设备通常具备一定溢价。"),
        "market_cap_research": _market_cap_research("当前更适合按精密设备补充映射理解。", "若量子设备链放量，可看重估。"),
        "segment_market_view": _segment_market_view("真空 / 精密设备环节可按数十亿美元级理解。", "公司份额适合按补充样本理解。", "中"),
    },
    "002008": {
        "selection_reason": _selection_reason("符合，因为它承接激光与光学设备，是量子光学链条的补充映射。", "方向成立，但更偏外围光学设备，不是最核心卖铲人。"),
        "scarcity_view": _scarcity_view("中", "激光设备有门槛，但量子纯度有限。"),
        "capacity_view": _capacity_view("中", "扩量看科研设备需求。"),
        "pricing_view": _pricing_view("结构升级", "利润改善更依赖高端科研设备占比提升。"),
        "market_cap_research": _market_cap_research("当前更适合按量子光学补充样本理解。", "若量子科研设备需求提升，可看重估。"),
        "segment_market_view": _segment_market_view("量子光学 / 激光设备补充环节可按数十亿美元级理解。", "公司份额适合按补充样本理解。", "中"),
    },
    "688800": {
        "selection_reason": _selection_reason("符合，因为它站在 AEC 高速组件 / 连接器这一层。", "方向正确，但更偏组件承接，纯度弱于核心映射。"),
        "scarcity_view": _scarcity_view("中", "高速组件有门槛，但替代难度低于核心芯片。"),
        "capacity_view": _capacity_view("中", "扩产更多受客户订单和组件验证影响。"),
        "pricing_view": _pricing_view("待验证", "价格弹性弱于连接芯片和 AEC DSP。"),
        "market_cap_research": _market_cap_research("当前更适合按高速组件观察样本理解。", "若 AEC 高速组件占比提升，可看补涨。"),
        "segment_market_view": _segment_market_view("高速组件 / 连接器环节可按数十亿美元级理解。", "公司份额适合按低中个位数理解。", "中"),
    },
    "300913": {
        "selection_reason": _selection_reason("符合，因为它受益于高速电缆及连接产品升级。", "更像受益层，而不是 CRDO 同层级卡点。"),
        "scarcity_view": _scarcity_view("中", "高规格电缆有门槛，但稀缺性弱于 AEC 芯片。"),
        "capacity_view": _capacity_view("中", "扩产与客户验证节奏相关，但不是最难环节。"),
        "pricing_view": _pricing_view("待验证", "价格能力取决于更高规格产品导入情况。"),
        "market_cap_research": _market_cap_research("当前更适合按高速电缆受益样本理解。", "若 224G/448G 验证推进，可看补涨。"),
        "segment_market_view": _segment_market_view("高速电缆及连接产品环节可按数十亿美元级理解。", "公司份额适合按低中个位数理解。", "中"),
    },
}


def _match(
    *,
    code: str,
    name: str,
    role: str,
    score: int,
    supply_chain_position: str,
    mapping_path: str,
    judgement: str,
    major_risk: str,
    source_validation: dict[str, Any] | None = None,
    selection_reason: dict[str, str] | None = None,
    scarcity_view: dict[str, str] | None = None,
    capacity_view: dict[str, str] | None = None,
    pricing_view: dict[str, str] | None = None,
    market_cap_research: dict[str, str] | None = None,
    segment_market_view: dict[str, str] | None = None,
) -> dict[str, Any]:
    source_meta = source_validation or _A_SHARE_SOURCE_VALIDATIONS.get(code) or _source_validation()
    metric_meta = _MATCH_SELECTION_METRICS.get(code, {})
    return {
        "code": code,
        "name": name,
        "display_name": f"{code} {name}",
        "role": role,
        "serenity_fit_score": score,
        "serenity_fit_level": _fit_level(score),
        "supply_chain_position": supply_chain_position,
        "mapping_path": mapping_path,
        "judgement": judgement,
        "major_risk": major_risk,
        "chart_url": build_chart_url("a", code),
        "chart_frequency_label": "主页图形",
        "analysis_detail_label": "查看个股分析",
        "analysis_detail_url": build_stock_analysis_detail_url(
            entity_type="match",
            identifier=code,
            display_name=f"{code} {name}",
            company_name=name,
            market="A",
        ),
        "financial_summary_short": "",
        "latest_news_preview": [],
        "analysis_source_label": "",
        "source_validation": source_meta,
        "selection_reason": selection_reason or metric_meta.get("selection_reason") or _selection_reason(judgement, mapping_path),
        "scarcity_view": scarcity_view or metric_meta.get("scarcity_view") or _scarcity_view("中", source_meta.get("summary") or supply_chain_position),
        "capacity_view": capacity_view or metric_meta.get("capacity_view") or _capacity_view("待验证", major_risk),
        "pricing_view": pricing_view or metric_meta.get("pricing_view") or _pricing_view("待验证", "当前更适合先跟踪供需与客户验证，价格传导待进一步确认。"),
        "market_cap_research": market_cap_research or metric_meta.get("market_cap_research") or _market_cap_research("研究市值待补充", "上行情形待补充"),
        "segment_market_view": segment_market_view or metric_meta.get("segment_market_view") or _segment_market_view(),
    }


def _related_stock(
    *,
    code: str,
    name: str,
    role: str,
    serenity_bucket: str,
    serenity_angle: str,
    stage: str,
    market_cap_hint: str,
    major_risk: str,
    source_validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "name": name,
        "display_name": f"{code} {name}",
        "role": role,
        "serenity_bucket": serenity_bucket,
        "serenity_angle": serenity_angle,
        "stage": stage,
        "market_cap_hint": market_cap_hint,
        "major_risk": major_risk,
        "chart_url": build_chart_url("a", code),
        "chart_frequency_label": "主页图形",
        "source_validation": source_validation or _A_SHARE_SOURCE_VALIDATIONS.get(code) or _source_validation(),
    }


def build_theme_related_detail_url(theme_slug: str, code: str) -> str:
    return f"/a_share_matches/theme-stock/{str(theme_slug or '').strip()}/{str(code or '').strip()}"


_THEME_RELATED_STOCKS: dict[str, list[dict[str, Any]]] = {
    "光模块 / CPO / 光子器件": [
        _related_stock(
            code="688498",
            name="源杰科技",
            role="EML/CW 光芯片",
            serenity_bucket="核心卡位",
            serenity_angle="更接近外置光源、CW 光源和硅光光源这些中期最容易卡住的上游器件层。",
            stage="客户验证 -> 收入放量",
            market_cap_hint="更像 100 亿级往上打开空间的上游器件票。",
            major_risk="CPO 与上游光芯片导入节奏慢于预期时，兑现会后移。",
            source_validation=_source_validation(
                summary="年报与业绩快报均验证数据中心 CW 光源和硅光光源订单改善。",
                sources=[
                    _source("源杰科技 2024 年报", "https://static.cninfo.com.cn/finalpage/2025-04-26/1223315239.PDF", "公司年报"),
                    _source("源杰科技 2025 业绩快报", "http://dataclouds.cninfo.com.cn/shgonggao/hsomarket/2026/20260227/0ce19c8acccc484eab6b690cb177a081.PDF", "业绩快报"),
                ],
            ),
        ),
        _related_stock(
            code="300308",
            name="中际旭创",
            role="800G/1.6T 光模块",
            serenity_bucket="核心现金流",
            serenity_angle="当前最强的已验证现金流仍在 800G/1.6T 可插拔模块，这一层决定短期业绩兑现。",
            stage="收入放量期",
            market_cap_hint="大市值龙头，空间更看 1.6T 交付和北美订单持续性。",
            major_risk="高估值对交付节奏与客户 capex 变化更敏感。",
            source_validation=_source_validation(
                summary="年报与财务决算同时验证 1.6T 产品落地和扩产备货。",
                sources=[
                    _source("中际旭创 2025 年报", "http://static.cninfo.com.cn/finalpage/2026-03-31/1225056459.PDF", "公司年报"),
                    _source("中际旭创 2025 财务决算", "https://static.cninfo.com.cn/finalpage/2026-03-31/1225056495.PDF", "财务决算"),
                ],
            ),
        ),
        _related_stock(
            code="300502",
            name="新易盛",
            role="高速光模块",
            serenity_bucket="核心现金流",
            serenity_angle="被 NVIDIA 官方生态点名，属于北美 AI 光模块链里最确定的国内交付样本之一。",
            stage="收入放量期",
            market_cap_hint="中大市值高弹性龙头，空间看订单与扩产兑现。",
            major_risk="客户集中与速率切换节奏会放大波动。",
            source_validation=_source_validation(
                summary="官方生态与公司 IR 同时验证了北美链身份和 2026 年持续交付。",
                sources=[
                    _source("NVIDIA Spectrum-X Photonics 官方新闻稿", "https://investor.nvidia.com/news/press-release-details/2025/NVIDIA-Announces-Spectrum-X-Photonics-Co-Packaged-Optics-Networking-Switches-to-Scale-AI-Factories-to-Millions-of-GPUs/default.aspx", "官方新闻稿"),
                    _source("新易盛 2026 年投资者关系记录", "http://static.cninfo.com.cn/finalpage/2026-04-24/1225178251.PDF", "投资者关系记录"),
                ],
            ),
        ),
        _related_stock(
            code="300394",
            name="天孚通信",
            role="FAU/光引擎/CPO 器件",
            serenity_bucket="关键受益",
            serenity_angle="比纯模块更接近 CPO 中期卡点，尤其是 FAU、ELS 和 1.6T 光引擎量产能力。",
            stage="收入放量期",
            market_cap_hint="中大市值平台股，空间看产品 mix 抬升而非纯题材拔估值。",
            major_risk="市场预期已经较高，若 CPO 放量偏慢则弹性会回落。",
            source_validation=_source_validation(
                summary="业绩与业绩说明会已验证 1.6T 光引擎量产和 CPO 配套开发。",
                sources=[
                    _source("天孚通信 2026 年投资者关系记录", "https://static.cninfo.com.cn/finalpage/2026-04-22/1225150075.PDF", "投资者关系记录"),
                    _source("天孚通信 2025 财务决算", "https://static.cninfo.com.cn/finalpage/2026-04-08/1225082716.PDF", "财务决算"),
                ],
            ),
        ),
        _related_stock(
            code="688313",
            name="仕佳光子",
            role="AWG/FAU/无源器件",
            serenity_bucket="观察候选",
            serenity_angle="AWG、平行光组件与高速光芯片让它更像 CPO 扩散阶段的关键配套层。",
            stage="主题识别 -> 客户验证",
            market_cap_hint="更像中小市值扩散受益股，弹性高但确定性弱于上游芯片。",
            major_risk="偏配套环节，若主线回落时通常回撤更快。",
            source_validation=_source_validation(
                summary="业绩快报和投资者交流都验证了 AWG/高速器件受 AI 数通拉动。",
                sources=[
                    _source("仕佳光子 2024 业绩快报", "https://static.cninfo.com.cn/finalpage/2025-02-28/1222661167.PDF", "业绩快报"),
                    _source("仕佳光子 2026 年投资者关系记录", "http://dataclouds.cninfo.com.cn/shgonggao/investor/2026/20260421/9d5951c23f3c4fb7a215c1f47e097047.PDF", "投资者关系记录"),
                ],
            ),
        ),
        _related_stock(
            code="002281",
            name="光迅科技",
            role="1.6T / 硅光平台",
            serenity_bucket="均衡映射",
            serenity_angle="国内链里兼具 1.6T 批量交付与硅光/CPO 储备的平台型映射。",
            stage="客户验证 -> 收入放量",
            market_cap_hint="中大市值一体化平台，空间看国内链和硅光产品放量。",
            major_risk="平台业务较宽，纯 AI 光互连弹性弱于更纯器件公司。",
            source_validation=_source_validation(
                summary="年报与业绩说明会都验证了 1.6T 批量交付和硅光/NPO 产品储备。",
                sources=[
                    _source("光迅科技 2025 年报摘要", "http://static.cninfo.com.cn/finalpage/2026-04-23/1225148211.PDF", "公司年报"),
                    _source("光迅科技 2026 年业绩说明会记录", "http://static.cninfo.com.cn/finalpage/2026-05-15/1225308047.PDF", "业绩说明会"),
                ],
            ),
        ),
        _related_stock(
            code="601869",
            name="长飞光纤",
            role="预制棒 / 光纤 / 空芯光纤",
            serenity_bucket="价格周期",
            serenity_angle="更像 AI 数据中心需求驱动下的价格周期与空芯光纤期权，和纯模块链不同，但能提供最直接的价格传导验证。",
            stage="价格上行 -> 利润兑现",
            market_cap_hint="中大市值光通信龙头，空间核心看光纤价格中枢、海外收入占比与空芯光纤商业化。",
            major_risk="运营商集采和海外需求若转弱，价格弹性会先收缩。",
            source_validation=_source_validation(
                summary="官方与权威媒体都验证了供需结构改善、毛利率抬升和空芯光纤商用推进。",
                sources=[
                    _source("长飞光纤 2025 年度行动方案评估报告", "https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2026-03-28/601869_20260328_KK43.pdf", "公司公告"),
                    _source("兴业证券聚焦长飞光纤景气拐点", "https://cj.sina.cn/article/norm_detail?url=https%3A%2F%2Ffinance.sina.com.cn%2Fstock%2Frelnews%2Fhk%2F2026-05-20%2Fdoc-inhyptai1675036.shtml", "权威媒体"),
                ],
            ),
        ),
    ],
    "光子材料 / 衬底 / 外延 / SOI": [
        _related_stock(
            code="688126",
            name="沪硅产业",
            role="SOI / 高端硅片",
            serenity_bucket="核心卡位",
            serenity_angle="直接对应高端基底 choke point，是硅光和高端器件底层平台型映射。",
            stage="客户验证 -> 利润兑现",
            market_cap_hint="更像 200-400 亿级平台资产，空间取决于高端产品渗透。",
            major_risk="高端良率与客户验证周期很长，兑现慢于题材热度。",
            source_validation=_source_validation(
                summary="Soitec 与中国授权框架延长，叠加卖方对 300mm SOI 量产与硅光验证的跟踪，验证其为 A 股 SOI 主映射。",
                sources=[
                    _source("Soitec FY26 Results", "https://www.soitec.com/home/group/newsroom/press-releases/content/2026/05/27/soitec-reports-fiscal-2026-full-year-results", "公司业绩公告"),
                    _source("Soitec 与 NSIG 授权延长", "https://www.soitec.com/home/group/newsroom/press-releases/content/2026/03/13/soitec-and-nsig-to-agree-extension-of-licensing-framework", "官方新闻稿"),
                ],
            ),
        ),
        _related_stock(
            code="002428",
            name="云南锗业",
            role="锗 / 化合物半导体材料",
            serenity_bucket="关键受益",
            serenity_angle="更纯的上游材料弹性，适合材料瓶颈被重估的阶段。",
            stage="主题识别 -> 客户验证",
            market_cap_hint="小中市值材料票，若关键材料属性被认知，弹性很大。",
            major_risk="资源价格波动会干扰产业链逻辑。",
            source_validation=_source_validation(
                summary="互动平台和媒体跟踪都验证其磷化铟衬底与扩产逻辑。",
                sources=[
                    _source("云南锗业互动平台问答", "https://irm.cninfo.com.cn/ircs/question/questionDetail?questionId=1995277988417691648", "互动平台"),
                    _source("证券时报：磷化铟价格与扩产跟踪", "https://stcn.com/article/detail/3930527.html", "权威媒体"),
                ],
            ),
        ),
        _related_stock(
            code="600703",
            name="三安光电",
            role="化合物半导体外延 / 芯片",
            serenity_bucket="观察候选",
            serenity_angle="平台能力完整，但业务面更宽，适合作为材料到器件一体化锚点。",
            stage="收入兑现期",
            market_cap_hint="大市值平台，空间更看业务结构优化。",
            major_risk="若继续被按传统 LED 框架理解，重估斜率有限。",
            source_validation=_source_validation(
                summary="官网产业链定位与公开口径都验证其在外延和高速光芯片的承接能力。",
                sources=[
                    _source("三安光电官网 About", "https://www.sanan-e.com/about-us", "公司官网"),
                    _source("三安光电高速光芯片出货报道", "https://finance.sina.com.cn/jjxw/2026-06-09/doc-iniauzks3246445.shtml", "权威媒体"),
                ],
            ),
        ),
    ],
    "AI互连 / 连接芯片 / AEC": [
        _related_stock(
            code="688008",
            name="澜起科技",
            role="CXL / 内存接口芯片",
            serenity_bucket="核心卡位",
            serenity_angle="最接近协议层与连接芯片的核心卡位，具备标准和平台双重壁垒。",
            stage="客户验证 -> 收入放量",
            market_cap_hint="中大市值连接芯片平台，空间随 CXL 商业化抬升。",
            major_risk="标准推进若慢于预期，市场会先下修想象空间。",
            source_validation=_source_validation(
                summary="年报和新品送样都验证其 PCIe/CXL Retimer 与 AEC 解决方案卡位。",
                sources=[
                    _source("澜起科技 2025 年报", "https://data.eastmoney.com/notices/detail/688008/AN202603301820868317.html", "公司年报"),
                    _source("澜起科技 PCIe 6/CXL 3 Retimer 送样", "https://tech.sina.cn/2025-01-22/detail-inefuxsi7325077.d.html?vt=4", "权威媒体"),
                ],
            ),
        ),
        _related_stock(
            code="605277",
            name="新亚电子",
            role="高速铜缆连接线",
            serenity_bucket="关键受益",
            serenity_angle="已经嵌进安费诺链条，是 A 股里少数有全球 AI 服务器验证的高速铜缆连接线样本。",
            stage="客户验证 -> 收入放量",
            market_cap_hint="偏中小市值供应链标的，空间看高速铜缆渗透与海外客户放量。",
            major_risk="本质仍是供应链受益，不是连接芯片本体，议价能力有限。",
            source_validation=_source_validation(
                summary="互动平台和年报相关报道均验证其通过安费诺切入全球 AI 服务器供应链。",
                sources=[
                    _source("证券日报：新亚电子高速铜缆连接线跟踪", "https://finance.eastmoney.com/a/202605133736167721.html", "权威媒体"),
                    _source("证券时报：新亚电子进入安费诺供应链", "https://m.10jqka.com.cn/20260429/c676395292.shtml", "权威媒体"),
                ],
            ),
        ),
        _related_stock(
            code="002130",
            name="沃尔核材",
            role="224G/448G 高速通信线",
            serenity_bucket="关键受益",
            serenity_angle="更像高速铜互连代际升级的受益者，直接承接 224G/448G 线材验证。",
            stage="客户验证 -> 收入放量",
            market_cap_hint="中等市值高速线材平台，空间看 448G 验证与海外客户放量。",
            major_risk="仍偏线材平台，离交换芯片和协议层卡点更远。",
            source_validation=_source_validation(
                summary="年报与互动平台都验证其 224G 稳定交付和 448G 重点客户验证。",
                sources=[
                    _source("沃尔核材 2025 年报", "http://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=12052599", "公司年报"),
                    _source("深交所互动易：高速通信线客户结构", "https://ir.p5w.net/question/00012333E8EC8A4E42049E2F8A928271F952.shtml", "互动平台"),
                ],
            ),
        ),
    ],
    "存储 / NAND / HBM": [
        _related_stock(
            code="688525",
            name="佰维存储",
            role="企业级存储 / 模组",
            serenity_bucket="核心卡位",
            serenity_angle="是 NAND 周期与产品化弹性结合得最直接的 A 股样本之一。",
            stage="价格修复 -> 收入放量",
            market_cap_hint="中等市值存储票，空间主要看周期与企业级结构优化。",
            major_risk="库存和价格波动会快速传导到盈利。",
        ),
        _related_stock(
            code="001309",
            name="德明利",
            role="控制器 / 模组",
            serenity_bucket="关键受益",
            serenity_angle="控制器叠加模组，比纯模组更有结构性，但仍属于周期弹性资产。",
            stage="价格修复期",
            market_cap_hint="偏中小市值，弹性大但更依赖价格趋势。",
            major_risk="若价格修复中断，业绩弹性会迅速回落。",
        ),
        _related_stock(
            code="301308",
            name="江波龙",
            role="存储模组 / 品牌",
            serenity_bucket="观察候选",
            serenity_angle="更像熟知度高的扩散标的，适合做主题热度温度计。",
            stage="收入放量期",
            market_cap_hint="中大市值模组平台，空间偏周期弹性而非技术壁垒。",
            major_risk="品牌和模组属性使其更容易受价格波动影响。",
        ),
    ],
    "算力 / 云基础设施 / GPU云": [
        _related_stock(
            code="603019",
            name="中科曙光",
            role="算力基础设施平台",
            serenity_bucket="核心卡位",
            serenity_angle="更接近供给侧算力平台，而不是单纯卖服务器，符合 Serenity 对平台资源层的偏好。",
            stage="客户验证 -> 收入放量",
            market_cap_hint="大市值平台型资产，空间看资源调度与平台能力增强。",
            major_risk="兑现仍受政策和资本开支节奏影响。",
        ),
        _related_stock(
            code="300738",
            name="奥飞数据",
            role="IDC / 机柜资源",
            serenity_bucket="关键受益",
            serenity_angle="属于 GPU 云基础设施承载层，是电力与算力扩张的直接受益者。",
            stage="收入放量期",
            market_cap_hint="中等市值资源票，空间随上架率和租赁价格变化。",
            major_risk="重资产扩张下，对资本开支和利用率很敏感。",
        ),
        _related_stock(
            code="000977",
            name="浪潮信息",
            role="AI 服务器整机",
            serenity_bucket="观察候选",
            serenity_angle="更偏部署层，不是最纯的 Serenity 审美，但适合观察主题资金扩散。",
            stage="收入兑现期",
            market_cap_hint="大市值整机龙头，空间更看行业景气与订单持续性。",
            major_risk="整机利润率和竞争压力制约估值抬升。",
        ),
    ],
    "晶圆代工 / 特色工艺": [
        _related_stock(
            code="688981",
            name="中芯国际",
            role="晶圆代工平台",
            serenity_bucket="核心卡位",
            serenity_angle="是最直接的 A 股 foundry 中枢映射，平台能力和产业地位最强。",
            stage="利润兑现期",
            market_cap_hint="千亿级平台资产，空间看先进制程与资本开支持续性。",
            major_risk="先进制程推进与地缘变量会反复影响估值。",
        ),
        _related_stock(
            code="688347",
            name="华虹公司",
            role="特色工艺代工",
            serenity_bucket="关键受益",
            serenity_angle="特色工艺更符合 Serenity 寻找细分制造错配的审美。",
            stage="收入兑现期",
            market_cap_hint="中大市值平台，空间看高附加值特色工艺占比。",
            major_risk="若市场只追先进逻辑，特色工艺相对收益偏弱。",
        ),
        _related_stock(
            code="688396",
            name="华润微",
            role="功率 / IDM 平台",
            serenity_bucket="观察候选",
            serenity_angle="更偏功率与成熟工艺平台，是特色工艺生态补充样本。",
            stage="利润兑现期",
            market_cap_hint="大市值 IDM 平台，空间更看结构优化。",
            major_risk="IDM 结构让映射纯度弱于 foundry 平台。",
        ),
    ],
    "先进封装 / 玻璃基板 / HBM设备": [
        _related_stock(
            code="688120",
            name="华海清科",
            role="先进封装工艺设备",
            serenity_bucket="核心卡位",
            serenity_angle="更接近先进封装主工艺设备，是典型设备 choke point。",
            stage="客户验证 -> 收入放量",
            market_cap_hint="中大市值设备平台，空间看先进封装设备渗透。",
            major_risk="设备验证慢，订单节奏受 capex 影响很大。",
        ),
        _related_stock(
            code="300604",
            name="长川科技",
            role="测试设备",
            serenity_bucket="关键受益",
            serenity_angle="属于封装后段关键装备，适合先进封装扩散逻辑。",
            stage="收入放量期",
            market_cap_hint="中等市值测试设备股，空间看国产替代和封装升级。",
            major_risk="测试设备更受资本开支周期波动影响。",
        ),
        _related_stock(
            code="603773",
            name="沃格光电",
            role="玻璃基板材料",
            serenity_bucket="观察候选",
            serenity_angle="更偏新材料路线期权，是玻璃基板主线的前瞻性样本。",
            stage="主题识别 -> 客户验证",
            market_cap_hint="中小市值新材料票，路线一旦验证弹性很大。",
            major_risk="路线验证仍早，产业投入与放量时间不确定。",
        ),
    ],
    "商业航天 / 卫星 / 发射": [
        _related_stock(
            code="600118",
            name="中国卫星",
            role="卫星系统平台",
            serenity_bucket="核心卡位",
            serenity_angle="在 A 股里最接近系统级航天平台，而不是单点配套。",
            stage="客户验证 -> 收入放量",
            market_cap_hint="中大市值系统平台，空间看商业航天渗透提升。",
            major_risk="商业化与体制订单的切换节奏偏慢。",
        ),
        _related_stock(
            code="600879",
            name="航天电子",
            role="航天电子配套",
            serenity_bucket="关键受益",
            serenity_angle="属于链条里较硬的关键配套，但系统平台属性弱于整星公司。",
            stage="收入兑现期",
            market_cap_hint="中等市值配套平台，空间取决于商业航天订单占比。",
            major_risk="更容易被当作传统军工配套而非商业航天标的。",
        ),
        _related_stock(
            code="300762",
            name="上海瀚讯",
            role="卫星通信应用",
            serenity_bucket="观察候选",
            serenity_angle="更偏生态受益和应用扩散，是商业航天热度传导时的观察点。",
            stage="主题识别期",
            market_cap_hint="中小市值应用票，空间受主题资金和订单共同影响。",
            major_risk="与发射和系统主线距离较远，容易受情绪驱动。",
        ),
    ],
    "电力 / 公用事业 / 电网设备": [
        _related_stock(
            code="600406",
            name="国电南瑞",
            role="电网自动化 / 调度系统",
            serenity_bucket="核心卡位",
            serenity_angle="最接近电网升级中枢，是 AI power bottleneck 在 A 股里最硬的映射之一。",
            stage="收入兑现期",
            market_cap_hint="大市值中枢平台，空间看电网 capex 上修。",
            major_risk="招标和电网投资节奏会影响兑现速度。",
        ),
        _related_stock(
            code="000400",
            name="许继电气",
            role="输配电关键设备",
            serenity_bucket="关键受益",
            serenity_angle="比泛公用事业更接近硬件 choke point，是电网设备升级的直接受益者。",
            stage="收入放量期",
            market_cap_hint="中大市值设备平台，空间看输配电升级周期。",
            major_risk="设备制造属性使其更依赖订单结构变化。",
        ),
        _related_stock(
            code="601179",
            name="中国西电",
            role="输变电设备",
            serenity_bucket="观察候选",
            serenity_angle="方向正确但偏广谱设备，更适合做电网投资扩散期观察。",
            stage="收入放量期",
            market_cap_hint="中等市值设备票，空间更多来自基建景气。",
            major_risk="设备同质化和盈利弹性会限制溢价。",
        ),
    ],
    "关键矿物 / 稀土 / 战略材料": [
        _related_stock(
            code="600111",
            name="北方稀土",
            role="稀土龙头 / 战略资源",
            serenity_bucket="核心卡位",
            serenity_angle="最符合关键矿物与战略资源卡位逻辑，是典型上游 choke point。",
            stage="主题识别 -> 客户验证",
            market_cap_hint="大市值资源平台，空间看战略材料重新定价。",
            major_risk="商品价格波动会掩盖长期战略属性。",
        ),
        _related_stock(
            code="600392",
            name="盛和资源",
            role="资源 + 加工一体化",
            serenity_bucket="关键受益",
            serenity_angle="资源与加工一体化更符合供应链自主可控的主线。",
            stage="客户验证期",
            market_cap_hint="中等市值资源加工平台，空间看稀缺性被认知。",
            major_risk="资源价格和海外供给扰动较大。",
        ),
        _related_stock(
            code="600259",
            name="广晟有色",
            role="稀土 / 有色资源",
            serenity_bucket="观察候选",
            serenity_angle="更偏综合资源平台，适合做战略材料扩散行情观察。",
            stage="主题识别期",
            market_cap_hint="中等市值资源票，空间受商品价格和政策预期共同影响。",
            major_risk="综合资源属性会削弱纯主线映射。",
        ),
    ],
    "机器人 / 具身智能 / 核心部件": [
        _related_stock(
            code="300124",
            name="汇川技术",
            role="运动控制 / 伺服平台",
            serenity_bucket="核心卡位",
            serenity_angle="最贴近具身智能执行器和运动控制的底层平台，是 A 股里更符合 Serenity 方法的硬件支点。",
            stage="客户验证 -> 收入放量",
            market_cap_hint="大市值自动化平台，空间看机器人渗透率和产品结构升级。",
            major_risk="自动化主业体量大，会稀释纯机器人映射弹性。",
        ),
        _related_stock(
            code="688017",
            name="绿的谐波",
            role="谐波减速器",
            serenity_bucket="关键受益",
            serenity_angle="减速器是具身智能执行链的核心部件之一，更接近真正的机械 choke point。",
            stage="客户验证期",
            market_cap_hint="中市值核心部件公司，空间看机器人本体放量和国产替代。",
            major_risk="中国替代链竞争加剧会压缩毛利和稀缺性溢价。",
        ),
        _related_stock(
            code="688333",
            name="铂力特",
            role="金属3D打印 / 结构制造",
            serenity_bucket="观察候选",
            serenity_angle="机器人骨架与复杂轻量结构需要新型制造工艺，金属增材是更符合 Serenity 的制造侧观察点。",
            stage="主题识别期",
            market_cap_hint="中市值先进制造平台，空间看结构件复杂度提升。",
            major_risk="机器人结构件需求兑现节奏可能慢于市场热度。",
        ),
    ],
    "量子计算 / 精密制造 / 上游设备": [
        _related_stock(
            code="688027",
            name="国盾量子",
            role="量子硬件 / 系统锚点",
            serenity_bucket="核心卡位",
            serenity_angle="虽然业务口径更广，但在 A 股里最接近量子硬件与系统层的直接锚点。",
            stage="主题识别 -> 客户验证",
            market_cap_hint="中市值量子系统公司，空间看量子硬件订单与产业验证。",
            major_risk="A 股量子口径混杂，容易被泛量子概念交易主导。",
        ),
        _related_stock(
            code="688167",
            name="炬光科技",
            role="精密激光 / 光源器件",
            serenity_bucket="关键受益",
            serenity_angle="量子器件、精密测控和光源路径都离不开高质量激光，是量子设备链里更贴近硬件上游的位置。",
            stage="客户验证期",
            market_cap_hint="中市值光源与微光学平台，空间看高端设备渗透。",
            major_risk="量子链需求占比仍小，短期更多依赖其他高端制造需求。",
        ),
        _related_stock(
            code="002158",
            name="汉钟精机",
            role="真空 / 压缩基础设备",
            serenity_bucket="观察候选",
            serenity_angle="量子计算前段工艺对真空与稳定设备依赖高，这类底层设备更符合 Serenity 的上游设备审美。",
            stage="主题识别期",
            market_cap_hint="中等市值设备平台，空间看高端制造需求外溢。",
            major_risk="真空设备映射是方法论相关，不是纯量子收入映射。",
        ),
    ],
}


def _stock(
    *,
    symbol: str,
    display_name: str,
    company_name: str,
    exchange: str,
    market: str,
    isin: str,
    numeric_code: str,
    theme_chip: str,
    research_summary: str,
    main_matches: list[dict[str, Any]],
    candidate_matches: list[dict[str, Any]],
    source_validation: dict[str, Any] | None = None,
    selection_reason: dict[str, str] | None = None,
    scarcity_view: dict[str, str] | None = None,
    capacity_view: dict[str, str] | None = None,
    pricing_view: dict[str, str] | None = None,
    market_cap_research: dict[str, str] | None = None,
    segment_market_view: dict[str, str] | None = None,
) -> dict[str, Any]:
    reason_data = _PROJECT_STOCK_REASON_DATA.get(symbol, {})
    note = get_project_tweet_note(symbol)
    source_meta = source_validation or _PROJECT_SOURCE_VALIDATIONS.get(symbol) or _source_validation()
    metric_meta = _PROJECT_SELECTION_METRICS.get(symbol, {})
    note_market_cap = note.get("market_cap_view") or {}
    scenarios = note_market_cap.get("scenarios") or []
    return {
        "symbol": symbol,
        "display_name": display_name,
        "company_name": company_name,
        "exchange": exchange,
        "market": market,
        "isin": isin,
        "numeric_code": numeric_code,
        "theme_chip": theme_chip,
        "research_summary": research_summary,
        "serenity_reason_summary": reason_data.get("serenity_reason_summary", research_summary),
        "serenity_reason_highlights": reason_data.get("serenity_reason_highlights", []),
        "tweet_detail_label": reason_data.get("tweet_detail_label", "查看推荐脉络"),
        "chart_url": "",
        "chart_unavailable_reason": "",
        "chart_frequency_label": "主页图形",
        "analysis_detail_label": "查看个股分析",
        "analysis_detail_url": build_stock_analysis_detail_url(
            entity_type="project",
            identifier=symbol,
            display_name=display_name,
            company_name=company_name,
            exchange=exchange,
            market=market,
            numeric_code=numeric_code,
        ),
        "financial_summary_short": "",
        "latest_news_preview": [],
        "analysis_source_label": "",
        "source_validation": source_meta,
        "selection_reason": selection_reason or metric_meta.get("selection_reason") or _selection_reason(
            reason_data.get("serenity_reason_summary", research_summary),
            research_summary,
        ),
        "scarcity_view": scarcity_view or metric_meta.get("scarcity_view") or _scarcity_view("中高", source_meta.get("summary") or research_summary),
        "capacity_view": capacity_view or metric_meta.get("capacity_view") or _capacity_view(
            "待验证",
            str((note.get("stage_view") or {}).get("next_step") or "扩产与客户验证仍需持续跟踪。"),
        ),
        "pricing_view": pricing_view or metric_meta.get("pricing_view") or _pricing_view("待验证", "价格传导需要结合供需、路线导入和客户验证继续判断。"),
        "market_cap_research": market_cap_research or metric_meta.get("market_cap_research") or _market_cap_research(
            str(note_market_cap.get("current_anchor") or "研究市值待补充"),
            str((scenarios[-1] if scenarios else {}).get("market_cap") or "上行情形待补充"),
        ),
        "segment_market_view": segment_market_view or metric_meta.get("segment_market_view") or _segment_market_view(),
        "stage_snapshot": {
            "name": str((note.get("stage_view") or {}).get("name") or ""),
            "next_step": str((note.get("stage_view") or {}).get("next_step") or ""),
        },
        "market_cap_snapshot": {
            "current_anchor": str((note.get("market_cap_view") or {}).get("current_anchor") or ""),
            "top_scenario": str((((note.get("market_cap_view") or {}).get("scenarios") or [{}])[-1]).get("market_cap") or ""),
        },
        "main_matches": main_matches,
        "candidate_matches": candidate_matches,
    }


def _theme_related_bucket_weight(bucket: str) -> int:
    normalized_bucket = str(bucket or "").strip()
    return {
        "核心卡位": 18,
        "核心现金流": 17,
        "关键受益": 14,
        "均衡映射": 12,
        "观察候选": 10,
        "价格周期": 9,
    }.get(normalized_bucket, 11)


def _build_theme_a_share_index(title: str, project_stocks: list[dict[str, Any]], related_stocks: list[dict[str, Any]]) -> dict[str, Any]:
    constituents: dict[str, dict[str, Any]] = {}

    def merge_constituent(
        *,
        code: str,
        name: str,
        weight: int | float,
        source_type: str,
    ) -> None:
        normalized_code = str(code or "").strip()
        if not normalized_code:
            return
        existing = constituents.get(normalized_code)
        if existing is None:
            constituents[normalized_code] = {
                "code": normalized_code,
                "name": str(name or "").strip(),
                "weight": float(weight),
                "source_type": source_type,
            }
            return
        existing["weight"] = float(existing.get("weight") or 0) + float(weight)

    for stock in project_stocks:
        for match in stock.get("main_matches", []):
            merge_constituent(
                code=str(match.get("code") or ""),
                name=str(match.get("name") or ""),
                weight=float(match.get("serenity_fit_score") or 0),
                source_type="main_match",
            )
        for match in stock.get("candidate_matches", []):
            merge_constituent(
                code=str(match.get("code") or ""),
                name=str(match.get("name") or ""),
                weight=max(float(match.get("serenity_fit_score") or 0), 6.0),
                source_type="candidate_match",
            )

    for item in related_stocks:
        merge_constituent(
            code=str(item.get("code") or ""),
            name=str(item.get("name") or ""),
            weight=_theme_related_bucket_weight(str(item.get("serenity_bucket") or "")),
            source_type="theme_related",
        )

    constituent_list = sorted(
        constituents.values(),
        key=lambda item: (-float(item.get("weight") or 0), str(item.get("code") or "")),
    )
    return {
        "slug": "",
        "name": f"{title} A股指数",
        "chart_title": f"{title} 历史价格图",
        "default_lookback_days": "max",
        "base_value": 1000.0,
        "sample_count": len(constituent_list),
        "weight_method": "Serenity Fit / 主题分层加权",
        "constituents": constituent_list,
        "codes_csv": ",".join(str(item.get("code") or "") for item in constituent_list),
        "weights_csv": ",".join(f"{item.get('code')}:{float(item.get('weight') or 0):.2f}" for item in constituent_list),
    }


def _theme(title: str, project_stocks: list[dict[str, Any]]) -> dict[str, Any]:
    theme_style = _THEME_ACCENTS.get(
        title,
        {
            "accent": "#7dd3fc",
            "accent_soft": "rgba(125, 211, 252, 0.12)",
            "accent_line": "rgba(125, 211, 252, 0.28)",
        },
    )
    slug = title.replace(" / ", "-").replace(" ", "").replace("/", "-")
    related_stocks = [
        {
            **item,
            "detail_url": build_theme_related_detail_url(slug, str(item.get("code") or "").strip()),
        }
        for item in _THEME_RELATED_STOCKS.get(title, [])
    ]
    return {
        "title": title,
        "slug": slug,
        "accent": theme_style["accent"],
        "accent_soft": theme_style["accent_soft"],
        "accent_line": theme_style["accent_line"],
        "a_share_index": {
            **_build_theme_a_share_index(title, project_stocks, related_stocks),
            "slug": slug,
        },
        "theme_related_stocks": related_stocks,
        "project_stocks": project_stocks,
        "related_stock_count": len(related_stocks),
        "project_stock_count": len(project_stocks),
    }


def get_theme_related_stock_detail(theme_slug: str, code: str) -> dict[str, Any] | None:
    normalized_slug = str(theme_slug or "").strip()
    normalized_code = str(code or "").strip()
    if not normalized_slug or not normalized_code:
        return None

    for theme in _THEMES:
        if str(theme.get("slug") or "").strip() != normalized_slug:
            continue
        for stock in theme.get("theme_related_stocks", []):
            if str(stock.get("code") or "").strip() == normalized_code:
                return {
                    "theme_title": str(theme.get("title") or ""),
                    "theme_slug": normalized_slug,
                    "theme_accent": str(theme.get("accent") or ""),
                    "theme_accent_soft": str(theme.get("accent_soft") or ""),
                    "theme_accent_line": str(theme.get("accent_line") or ""),
                    "stock": dict(stock),
                }
    return None


_THEMES: list[dict[str, Any]] = [
    _theme(
        "光模块 / CPO / 光子器件",
        [
            _stock(
                symbol="SIVE",
                display_name="Sivers Semiconductors",
                company_name="Sivers Semiconductors AB",
                exchange="OMXSTO",
                market="Sweden/US",
                isin="SE0003917798",
                numeric_code="-",
                theme_chip="Photonics / laser bottleneck / CPO upstream",
                research_summary="更像 Serenity 原始审美的 photonics 上游名字，应优先映射到光芯片、激光与微光学这些更靠近 choke point 的环节，而不是仅映射高速模组受益股。",
                main_matches=[
                    _match(
                        code="688498",
                        name="源杰科技",
                        role="CW/EML光芯片",
                        score=18,
                        supply_chain_position="上游光芯片",
                        mapping_path="SIVE -> laser / CPO upstream -> A股光芯片",
                        judgement="更接近 Serenity 偏好的上游核心器件 choke point，逻辑强于单纯模组受益。",
                        major_risk="下游 CPO 放量节奏若偏慢，业绩兑现与估值切换会后移。",
                    ),
                    _match(
                        code="688167",
                        name="炬光科技",
                        role="微光学/CPO相关",
                        score=15,
                        supply_chain_position="微光学 / 激光相关",
                        mapping_path="SIVE -> 激光链路 -> 微光学环节",
                        judgement="有 Serenity 风格，但需继续验证其在量产链条中是否属于真正难替代的关键段。",
                        major_risk="若更多停留在相关配套而非核心卡位，分数会向中高回落。",
                    ),
                ],
                candidate_matches=[
                    _match(
                        code="688313",
                        name="仕佳光子",
                        role="AWG/CW/FAU",
                        score=14,
                        supply_chain_position="耦合与无源器件",
                        mapping_path="SIVE -> 光连接 / 耦合器件 -> A股配套",
                        judgement="强相关但更像关键受益环节，未必是最核心的 Serenity choke point。",
                        major_risk="产品位置偏配套，若客户结构变化则弹性不如上游光芯片。",
                    ),
                    _match(
                        code="300394",
                        name="天孚通信",
                        role="FAU/光引擎/CPO器件",
                        score=13,
                        supply_chain_position="光引擎 / 器件平台",
                        mapping_path="SIVE -> CPO器件 / 光引擎 -> A股受益层",
                        judgement="高质量受益股，但在 Serenity 框架下更偏收益层，不是最上游卡位层。",
                        major_risk="市场认知度已高，若新平台放量不超预期，估值继续抬升会受限。",
                    ),
                ],
            ),
            _stock(
                symbol="LITE",
                display_name="Lumentum",
                company_name="Lumentum Holdings Inc.",
                exchange="NASDAQ",
                market="US",
                isin="US55024U1097",
                numeric_code="-",
                theme_chip="CPO / optical components / photonics platform",
                research_summary="平台型 photonics 龙头适合映射到 A 股中的器件平台和少数光芯片能力股，但需要把最上游器件与纯模组区分开。",
                main_matches=[
                    _match(
                        code="300394",
                        name="天孚通信",
                        role="CPO器件/光引擎",
                        score=16,
                        supply_chain_position="器件平台 / 光引擎",
                        mapping_path="LITE -> CPO器件平台 -> A股器件平台",
                        judgement="平台属性最接近，能承接 Lumentum 在光器件与 CPO 平台上的映射逻辑。",
                        major_risk="平台型业务覆盖广，若 CPO 占比提升不及预期，纯 Serenity 叙事浓度会下降。",
                    ),
                    _match(
                        code="002281",
                        name="光迅科技",
                        role="光芯片+光模块",
                        score=15,
                        supply_chain_position="器件到模块一体化",
                        mapping_path="LITE -> 光芯片 / 光器件平台 -> A股一体化平台",
                        judgement="比纯模组更接近 LITE 的全栈属性，但仍带有较强平台型国企特征。",
                        major_risk="业务面较宽，若市场转向追逐更纯粹的上游卡位，弹性可能弱于细分龙头。",
                    ),
                ],
                candidate_matches=[
                    _match(
                        code="300308",
                        name="中际旭创",
                        role="高速光模块",
                        score=12,
                        supply_chain_position="高速光模块",
                        mapping_path="LITE -> 光模块平台 -> A股高速模组",
                        judgement="是核心受益龙头，但更偏下游模组环节，不是最典型 Serenity 上游映射。",
                        major_risk="市场已充分认知 AI 光模块主线，预期差主要来自景气持续性。",
                    ),
                    _match(
                        code="300502",
                        name="新易盛",
                        role="高速光模块",
                        score=12,
                        supply_chain_position="高速光模块",
                        mapping_path="LITE -> 光模块平台 -> A股高速模组",
                        judgement="受益逻辑清楚，但更适合作为候选池而非主映射。",
                        major_risk="若下游需求波动，模组价格与出货节奏对业绩影响更直接。",
                    ),
                ],
            ),
            _stock(
                symbol="AAOI",
                display_name="Applied Optoelectronics",
                company_name="Applied Optoelectronics, Inc.",
                exchange="NASDAQ",
                market="US",
                isin="US03823U1025",
                numeric_code="-",
                theme_chip="Optical transceivers / lasers / AI photonics",
                research_summary="AAOI 兼具 transceiver 与激光链条特征，A 股映射宜突出器件与光引擎，而不是把全部权重放到高速模组本身。",
                main_matches=[
                    _match(
                        code="300394",
                        name="天孚通信",
                        role="FAU/光引擎/CPO器件",
                        score=16,
                        supply_chain_position="光引擎 / 核心器件",
                        mapping_path="AAOI -> 激光 / 光引擎 -> A股器件平台",
                        judgement="最能承接 AAOI 在激光与器件平台之间的桥梁属性。",
                        major_risk="若 AI 光互连需求阶段性回落，器件弹性也会同步收敛。",
                    ),
                    _match(
                        code="002281",
                        name="光迅科技",
                        role="光芯片+光模块",
                        score=15,
                        supply_chain_position="一体化光通信平台",
                        mapping_path="AAOI -> transceiver / laser platform -> A股一体化平台",
                        judgement="在 A 股里属于更完整的平台映射，但气质仍弱于纯上游卡位。",
                        major_risk="平台型属性会稀释单一 AI 光互连的弹性。",
                    ),
                ],
                candidate_matches=[
                    _match(
                        code="300308",
                        name="中际旭创",
                        role="高速光模块",
                        score=12,
                        supply_chain_position="高速光模块",
                        mapping_path="AAOI -> 光模块 -> A股模组龙头",
                        judgement="强受益但更偏景气跟随，不是 Serenity 最偏好的上游定位。",
                        major_risk="估值与订单节奏对市场预期敏感度较高。",
                    ),
                    _match(
                        code="300502",
                        name="新易盛",
                        role="高速光模块",
                        score=12,
                        supply_chain_position="高速光模块",
                        mapping_path="AAOI -> 光模块 -> A股模组龙头",
                        judgement="属于同主线高弹性标的，但更像候选池受益层。",
                        major_risk="模组价格竞争与客户结构变化会放大业绩波动。",
                    ),
                ],
            ),
            _stock(
                symbol="COHR",
                display_name="Coherent",
                company_name="Coherent Corp.",
                exchange="NYSE",
                market="US",
                isin="US19247G1076",
                numeric_code="-",
                theme_chip="Lasers / optical components / datacom photonics",
                research_summary="Coherent 的核心是激光与光器件平台，映射时应优先找能承接激光器、核心器件与平台能力的 A 股，而不是只找高速模组。",
                main_matches=[
                    _match(
                        code="300394",
                        name="天孚通信",
                        role="光器件/CPO器件平台",
                        score=16,
                        supply_chain_position="器件平台",
                        mapping_path="COHR -> 激光 / 光器件平台 -> A股器件平台",
                        judgement="平台属性和多品类光器件定位最接近，是更合理的主映射。",
                        major_risk="若市场继续追逐更纯器件 choke point，平台股溢价可能落后。",
                    ),
                    _match(
                        code="002281",
                        name="光迅科技",
                        role="光芯片+光器件平台",
                        score=15,
                        supply_chain_position="光器件 / 光芯片平台",
                        mapping_path="COHR -> 光器件平台 -> A股一体化光器件",
                        judgement="更像平台映射而非单点瓶颈映射，适合作为共同主映射。",
                        major_risk="传统通信链业务占比仍会影响 AI 主线纯度。",
                    ),
                ],
                candidate_matches=[
                    _match(
                        code="300308",
                        name="中际旭创",
                        role="高速光模块平台",
                        score=12,
                        supply_chain_position="高速光模块",
                        mapping_path="COHR -> datacom photonics -> A股模组龙头",
                        judgement="更多是受益层映射，适合放在候选池而不是主映射。",
                        major_risk="模组景气变化会比器件平台更快传导到估值。",
                    ),
                ],
            ),
            _stock(
                symbol="POET",
                display_name="POET Technologies",
                company_name="POET Technologies Inc.",
                exchange="NASDAQ",
                market="US/Canada",
                isin="CA73044W1041",
                numeric_code="-",
                theme_chip="Optical engines / external light source / photonic integration",
                research_summary="POET 更强调外部光源与光引擎集成，A 股映射应围绕光引擎、耦合器件和光芯片链条展开，而不是只对应泛光模块。",
                main_matches=[
                    _match(
                        code="300394",
                        name="天孚通信",
                        role="光引擎/FAU/CPO器件",
                        score=17,
                        supply_chain_position="光引擎 / 耦合器件",
                        mapping_path="POET -> optical engine / external light source -> A股光引擎",
                        judgement="最贴近 POET 的光引擎与器件整合路线，适合放在主映射首位。",
                        major_risk="若相关平台导入不及预期，市场会重新回到传统光器件估值框架。",
                    ),
                    _match(
                        code="688498",
                        name="源杰科技",
                        role="CW/EML光芯片",
                        score=16,
                        supply_chain_position="上游光芯片",
                        mapping_path="POET -> external light source -> A股光芯片",
                        judgement="比模组更接近外部光源和核心光芯片逻辑，符合 Serenity 的上游偏好。",
                        major_risk="若平台方案没有明确拉动上游光芯片需求，映射强度会下降。",
                    ),
                ],
                candidate_matches=[
                    _match(
                        code="688313",
                        name="仕佳光子",
                        role="AWG/CW/FAU",
                        score=14,
                        supply_chain_position="耦合器件 / 无源器件",
                        mapping_path="POET -> 光引擎配套 -> A股耦合器件",
                        judgement="相关性强，但更偏配套层，适合作为候选池补充。",
                        major_risk="若导入节奏偏慢，配套环节弹性通常不及上游光芯片。",
                    ),
                ],
            ),
        ],
    ),
    _theme(
        "光子材料 / 衬底 / 外延 / SOI",
        [
            _stock(
                symbol="AXTI",
                display_name="AXT Inc",
                company_name="AXT, Inc.",
                exchange="NASDAQ",
                market="US",
                isin="US00246W1036",
                numeric_code="-",
                theme_chip="InP substrate / compound semiconductor materials",
                research_summary="AXT 属于更标准的上游材料链映射，应该优先寻找衬底、III-V 材料和光芯片材料这些 A 股上的材料 choke point。",
                main_matches=[
                    _match(
                        code="600703",
                        name="三安光电",
                        role="III-V化合物半导体/光芯片",
                        score=16,
                        supply_chain_position="化合物半导体材料到器件",
                        mapping_path="AXTI -> InP / III-V materials -> A股化合物半导体平台",
                        judgement="既承接材料逻辑，又具备器件延展性，是更完整的主映射。",
                        major_risk="平台业务较宽，若市场只追逐纯材料端，溢价不一定最陡。",
                    ),
                    _match(
                        code="002428",
                        name="云南锗业",
                        role="锗材料/化合物半导体材料",
                        score=15,
                        supply_chain_position="关键上游材料",
                        mapping_path="AXTI -> compound semiconductor materials -> A股锗与材料链",
                        judgement="更纯上游材料逻辑，符合 Serenity 对资源与材料 choke point 的偏好。",
                        major_risk="产业兑现更依赖下游化合物半导体扩产和良率提升。",
                    ),
                ],
                candidate_matches=[
                    _match(
                        code="002222",
                        name="福晶科技",
                        role="激光与光学晶体材料",
                        score=12,
                        supply_chain_position="光学晶体材料",
                        mapping_path="AXTI -> 光子材料 -> A股晶体材料",
                        judgement="相关但不是最直接的 InP / III-V 映射，更适合候选池。",
                        major_risk="材料方向更偏激光晶体，和 AXT 的复合半导体主线不完全一致。",
                    ),
                ],
            ),
            _stock(
                symbol="IQE",
                display_name="IQE",
                company_name="IQE plc",
                exchange="LSE",
                market="UK",
                isin="GB0009619924",
                numeric_code="-",
                theme_chip="Epiwafer / compound semiconductor upstream",
                research_summary="IQE 的核心是 epiwafer 和化合物半导体上游，映射时应优先外延与上游材料，而不是泛 LED 或普通封装。",
                main_matches=[
                    _match(
                        code="600703",
                        name="三安光电",
                        role="化合物半导体外延/芯片",
                        score=17,
                        supply_chain_position="外延片 / 化合物半导体平台",
                        mapping_path="IQE -> epiwafer / compound semiconductor -> A股外延与芯片平台",
                        judgement="在 A 股中最接近外延片和化合物半导体量产平台，是自然的主映射。",
                        major_risk="若市场把其视为传统 LED 平台，Serenity 风格溢价会受限。",
                    ),
                    _match(
                        code="002428",
                        name="云南锗业",
                        role="化合物半导体材料",
                        score=15,
                        supply_chain_position="关键上游材料",
                        mapping_path="IQE -> 外延上游材料 -> A股材料端",
                        judgement="更纯上游材料链，具备 Serenity 喜欢的材料稀缺属性。",
                        major_risk="对下游导入节奏较敏感，且市场预期常受资源价格扰动。",
                    ),
                ],
                candidate_matches=[
                    _match(
                        code="300323",
                        name="华灿光电",
                        role="LED/化合物半导体外延",
                        score=12,
                        supply_chain_position="外延与器件",
                        mapping_path="IQE -> 外延片 -> A股外延平台",
                        judgement="方向相关，但业务纯度和 Serenity 叙事一致性弱于主映射。",
                        major_risk="更多受常规 LED 与传统景气影响，AI 光子属性不够纯。",
                    ),
                ],
            ),
            _stock(
                symbol="SOI",
                display_name="Soitec",
                company_name="Soitec",
                exchange="EPA",
                market="France",
                isin="FR0013227113",
                numeric_code="-",
                theme_chip="SOI substrates / silicon photonics substrate monopoly",
                research_summary="Soitec 典型对应高端基底与 SOI 衬底垄断逻辑，主映射应优先放在 SOI / 高端硅片，而不是泛半导体材料。",
                main_matches=[
                    _match(
                        code="688126",
                        name="沪硅产业",
                        role="半导体硅片/SOI材料",
                        score=18,
                        supply_chain_position="SOI / 高端硅片基底",
                        mapping_path="SOI -> silicon photonics substrate -> A股 SOI 硅片",
                        judgement="是最直接的 A 股 SOI 映射，也最贴近 Serenity 的基底 choke point 审美。",
                        major_risk="高端产品兑现依赖客户验证与良率爬坡，节奏慢于题材交易。",
                    ),
                    _match(
                        code="605358",
                        name="立昂微",
                        role="半导体硅片",
                        score=15,
                        supply_chain_position="高端硅片",
                        mapping_path="SOI -> 高端晶圆基底 -> A股硅片平台",
                        judgement="虽不如沪硅直接，但仍属于高端硅片链的重要承接者。",
                        major_risk="SOI 纯度和直接性弱于主映射第一名。",
                    ),
                ],
                candidate_matches=[
                    _match(
                        code="688233",
                        name="神工股份",
                        role="半导体硅材料",
                        score=12,
                        supply_chain_position="半导体硅材料",
                        mapping_path="SOI -> 高端硅材料 -> A股材料端",
                        judgement="更像基底材料延伸映射，适合作为候选池补充。",
                        major_risk="和 Soitec 的直接 SOI 垄断逻辑相比，映射路径更长。",
                    ),
                ],
            ),
        ],
    ),
    _theme(
        "AI互连 / 连接芯片 / AEC",
        [
            _stock(
                symbol="AVGO",
                display_name="Broadcom",
                company_name="Broadcom Inc.",
                exchange="NASDAQ",
                market="US",
                isin="US11135F1012",
                numeric_code="-",
                theme_chip="AI Ethernet switch / scale-up fabric / network silicon",
                research_summary="Broadcom 在这个主题里不是泛半导体大盘股，而是 AI Ethernet 交换芯片和 scale-up fabric 的核心锚点。真正更接近互连约束的是交换芯片和网络栈，而不是只看铜缆或连接器组装。",
                main_matches=[
                    _match(
                        code="688008",
                        name="澜起科技",
                        role="CXL / Retimer / 连接芯片",
                        score=17,
                        supply_chain_position="连接芯片 / 协议层",
                        mapping_path="AVGO -> AI Ethernet / network silicon -> A股连接芯片平台",
                        judgement="A 股里最接近底层连接芯片卡位的样本，虽然不完全等同于交换芯片，但更贴近协议和系统互连层。",
                        major_risk="CXL 与连接芯片推进节奏若低于预期，想象空间会回摆。",
                    ),
                    _match(
                        code="688702",
                        name="盛科通信-U",
                        role="交换芯片 / 网络 fabric",
                        score=15,
                        supply_chain_position="交换芯片 / fabric 层",
                        mapping_path="AVGO -> AI Ethernet switch -> A股交换芯片",
                        judgement="更直接承接 AI Ethernet switch 的映射，但客户导入和竞争格局仍需要持续验证。",
                        major_risk="交换芯片路线验证与客户突破不确定性更高。",
                    ),
                ],
                candidate_matches=[
                    _match(
                        code="605277",
                        name="新亚电子",
                        role="高速铜缆连接线",
                        score=13,
                        supply_chain_position="高速铜互连承载层",
                        mapping_path="AVGO -> AI networking rollout -> A股高速铜缆连接线",
                        judgement="更像互连扩容带来的供应链受益，而不是 Broadcom 同层级卡点。",
                        major_risk="仍偏供应链受益，订单与毛利受客户结构影响较大。",
                    ),
                    _match(
                        code="002130",
                        name="沃尔核材",
                        role="224G/448G 高速通信线",
                        score=12,
                        supply_chain_position="高速铜互连承载层",
                        mapping_path="AVGO -> AI networking rollout -> A股高速通信线",
                        judgement="受益逻辑清楚，但更偏代际升级的承载层，地位弱于芯片本体。",
                        major_risk="448G 验证节奏若放慢，市场热度会回落更快。",
                    ),
                ],
            ),
            _stock(
                symbol="ALAB",
                display_name="Astera Labs",
                company_name="Astera Labs, Inc.",
                exchange="NASDAQ",
                market="US",
                isin="US04626A1034",
                numeric_code="-",
                theme_chip="AI connectivity / CXL / PCIe retimers and switches",
                research_summary="ALAB 更偏 AI 服务器互连芯片与协议层机会，主映射应优先选择具备互连芯片、交换与接口卡位的 A 股，而不是纯材料受益。",
                main_matches=[
                    _match(
                        code="688008",
                        name="澜起科技",
                        role="内存接口/CXL/服务器互连",
                        score=18,
                        supply_chain_position="接口芯片 / 互连协议层",
                        mapping_path="ALAB -> CXL / memory interconnect -> A股接口芯片",
                        judgement="是最像 Serenity 逻辑的直接芯片卡位，兼具协议壁垒和平台导入属性。",
                        major_risk="若 CXL 商业化节奏低于预期，市场可能重新按传统接口芯片估值。",
                    ),
                    _match(
                        code="688515",
                        name="裕太微-U",
                        role="高速以太网PHY/连接芯片",
                        score=15,
                        supply_chain_position="高速连接芯片",
                        mapping_path="ALAB -> 高速互连 -> A股 PHY / 连接芯片",
                        judgement="更偏单点连接芯片，虽不如澜起全面，但更接近底层互连器件卡位。",
                        major_risk="商业化和客户突破仍需时间，节奏不确定性较高。",
                    ),
                ],
                candidate_matches=[
                    _match(
                        code="688702",
                        name="盛科通信-U",
                        role="交换芯片/数据中心网络",
                        score=14,
                        supply_chain_position="交换芯片 / 网络层",
                        mapping_path="ALAB -> switch / network fabric -> A股交换芯片",
                        judgement="方向一致，但更偏网络交换侧，而非 Astera 最核心的接口和 retimer 逻辑。",
                        major_risk="行业竞争与客户拓展对节奏影响较大。",
                    ),
                ],
            ),
            _stock(
                symbol="CRDO",
                display_name="Credo Technology",
                company_name="Credo Technology Group Holding Ltd",
                exchange="NASDAQ",
                market="US",
                isin="KYG254571055",
                numeric_code="-",
                theme_chip="AEC / copper connectivity / high-speed interconnect",
                research_summary="Credo 更像 AEC 与高速铜互连的直接锚点，A 股映射要优先找已经进入全球服务器链的高速铜缆和高速通信线，而不是泛 PCB 跟随股。",
                main_matches=[
                    _match(
                        code="605277",
                        name="新亚电子",
                        role="高速铜缆连接线",
                        score=16,
                        supply_chain_position="高速铜互连承载层",
                        mapping_path="CRDO -> AEC / copper connectivity -> A股高速铜缆连接线",
                        judgement="已经通过安费诺进入全球服务器与数据中心链条，是 A 股里更接近 Credo 商业兑现路径的样本。",
                        major_risk="供应链属性仍强于芯片属性，议价能力和客户结构变化会影响弹性。",
                    ),
                    _match(
                        code="002130",
                        name="沃尔核材",
                        role="224G/448G 高速通信线",
                        score=14,
                        supply_chain_position="高速通信线 / 铜互连",
                        mapping_path="CRDO -> AEC / high-speed copper -> A股高速通信线",
                        judgement="224G 已稳定交付、448G 进入重点客户验证，受益于高速铜互连代际升级。",
                        major_risk="仍是供应链映射，若铜互连窗口缩短，估值弹性会先被压缩。",
                    ),
                ],
                candidate_matches=[
                    _match(
                        code="688800",
                        name="瑞可达",
                        role="AEC 高速组件 / 连接器",
                        score=12,
                        supply_chain_position="高速连接器 / 组件",
                        mapping_path="CRDO -> AEC supply chain -> A股高速组件",
                        judgement="方向正确但当前主题纯度一般，更适合做观察位而非主仓映射。",
                        major_risk="通信连接器占比不高，主题纯度不足会压制重估速度。",
                    ),
                    _match(
                        code="300913",
                        name="兆龙互连",
                        role="高速电缆及连接产品",
                        score=11,
                        supply_chain_position="高速电缆 / 连接产品",
                        mapping_path="CRDO -> AEC supply chain -> A股高速电缆",
                        judgement="更像高速电缆受益样本，但 224G/448G 仍处于验证推进阶段。",
                        major_risk="客户验证和订单节奏慢时，容易回落到普通线缆估值。",
                    ),
                ],
            ),
        ],
    ),
    _theme(
        "存储 / NAND / HBM",
        [
            _stock(
                symbol="SNDK",
                display_name="SanDisk",
                company_name="Sandisk Corporation",
                exchange="NASDAQ",
                market="US",
                isin="US80004C2008",
                numeric_code="-",
                theme_chip="NAND repricing / memory cycle",
                research_summary="SanDisk 这条线更偏 NAND 周期与重定价，A 股里应区分真正受价格上行拉动的模组、控制器和设计，而不是把所有存储股平铺。",
                main_matches=[
                    _match(
                        code="688525",
                        name="佰维存储",
                        role="存储器/模组",
                        score=15,
                        supply_chain_position="模组 / 企业级存储",
                        mapping_path="SNDK -> NAND cycle -> A股存储模组与产品化",
                        judgement="更能承接 NAND 周期修复与产品化弹性，是较合理的主映射。",
                        major_risk="模组链条对价格波动和库存周期的敏感度较高。",
                    ),
                    _match(
                        code="001309",
                        name="德明利",
                        role="存储控制器/模组",
                        score=14,
                        supply_chain_position="控制器 / 模组",
                        mapping_path="SNDK -> NAND + controller -> A股控制器与模组",
                        judgement="比单纯模组更具结构性，但稳定性依赖下游客户拓展。",
                        major_risk="价格修复若不持续，控制器与模组的盈利弹性会明显收敛。",
                    ),
                ],
                candidate_matches=[
                    _match(
                        code="301308",
                        name="江波龙",
                        role="存储模组/NAND产业链",
                        score=13,
                        supply_chain_position="模组 / 品牌",
                        mapping_path="SNDK -> NAND cycle -> A股模组品牌",
                        judgement="逻辑顺畅，但市场熟悉度较高，更适合候选池而非主映射。",
                        major_risk="品牌与模组属性决定其受库存周期扰动更大。",
                    ),
                    _match(
                        code="603986",
                        name="兆易创新",
                        role="存储芯片设计",
                        score=12,
                        supply_chain_position="存储芯片设计",
                        mapping_path="SNDK -> memory repricing -> A股存储设计",
                        judgement="更偏泛存储景气映射，不是最直接的 NAND 周期映射。",
                        major_risk="业务结构较宽，SanDisk 的纯 NAND 主线映射并不完全重合。",
                    ),
                ],
            ),
        ],
    ),
    _theme(
        "算力 / 云基础设施 / GPU云",
        [
            _stock(
                symbol="NBIS",
                display_name="Nebius Group",
                company_name="Nebius Group N.V.",
                exchange="NASDAQ",
                market="US",
                isin="NL0009805522",
                numeric_code="-",
                theme_chip="AI cloud / neocloud / AI infrastructure",
                research_summary="Nebius 更偏 neocloud 与算力基础设施，不是最标准的硬科技上游，但可映射到算力基础设施与 IDC 中更具资源与平台能力的 A 股。",
                main_matches=[
                    _match(
                        code="603019",
                        name="中科曙光",
                        role="AI服务器/算力基础设施",
                        score=16,
                        supply_chain_position="算力基础设施平台",
                        mapping_path="NBIS -> neocloud / AI infra -> A股算力平台",
                        judgement="更接近算力平台和基础设施供给侧，而不是单纯 IDC 租赁。",
                        major_risk="算力建设节奏与政策导向会共同影响业绩兑现。",
                    ),
                    _match(
                        code="300738",
                        name="奥飞数据",
                        role="IDC/算力基础设施",
                        score=13,
                        supply_chain_position="IDC / 机柜资源",
                        mapping_path="NBIS -> GPU cloud infra -> A股 IDC 承载层",
                        judgement="属于受益链条中较直接的资源层，但上游 choke point 属性不强。",
                        major_risk="机柜上架与资本开支节奏对业绩影响很大。",
                    ),
                ],
                candidate_matches=[
                    _match(
                        code="000977",
                        name="浪潮信息",
                        role="AI服务器",
                        score=13,
                        supply_chain_position="服务器整机",
                        mapping_path="NBIS -> AI compute deployment -> A股服务器",
                        judgement="更多是算力部署受益股，符合度不如算力平台与资源层。",
                        major_risk="整机属性较强，盈利受客户招标和价格竞争影响更大。",
                    ),
                    _match(
                        code="300383",
                        name="光环新网",
                        role="IDC/云计算基础设施",
                        score=12,
                        supply_chain_position="IDC / 云基础设施",
                        mapping_path="NBIS -> cloud infra -> A股 IDC",
                        judgement="方向相关，但更像传统 IDC 映射，Serenity 风格较弱。",
                        major_risk="传统 IDC 估值框架会压制纯 AI 叙事溢价。",
                    ),
                ],
            ),
        ],
    ),
    _theme(
        "晶圆代工 / 特色工艺",
        [
            _stock(
                symbol="TSM",
                display_name="Taiwan Semiconductor",
                company_name="Taiwan Semiconductor Manufacturing Company Limited",
                exchange="NYSE",
                market="Taiwan",
                isin="US8740391003",
                numeric_code="2330",
                theme_chip="Advanced logic / foundry / AI semiconductor anchor",
                research_summary="TSM 是 AI 半导体锚点，A 股映射应优先找最具平台能力的晶圆代工与特色工艺承接者，而不是泛半导体制造。",
                main_matches=[
                    _match(
                        code="688981",
                        name="中芯国际",
                        role="晶圆代工平台",
                        score=17,
                        supply_chain_position="先进逻辑代工平台",
                        mapping_path="TSM -> foundry anchor -> A股晶圆代工平台",
                        judgement="是最直接的 A 股代工平台映射，虽然先进制程差距仍在，但平台属性最接近。",
                        major_risk="资本开支与制程推进节奏会持续影响估值兑现。",
                    ),
                    _match(
                        code="688347",
                        name="华虹公司",
                        role="特色工艺代工",
                        score=15,
                        supply_chain_position="特色工艺代工",
                        mapping_path="TSM -> specialty / mature foundry -> A股特色工艺",
                        judgement="更偏成熟与特色工艺承接，适合作为共同主映射。",
                        major_risk="AI 主线纯度不如先进逻辑代工，高端逻辑溢价传导有限。",
                    ),
                ],
                candidate_matches=[
                    _match(
                        code="688249",
                        name="晶合集成",
                        role="晶圆代工",
                        score=12,
                        supply_chain_position="晶圆代工",
                        mapping_path="TSM -> foundry ecosystem -> A股晶圆代工",
                        judgement="逻辑成立但平台与先进逻辑代表性弱于前两者。",
                        major_risk="受单一产线结构和景气波动影响更大。",
                    ),
                ],
            ),
            _stock(
                symbol="TSEM",
                display_name="Tower Semiconductor",
                company_name="Tower Semiconductor Ltd.",
                exchange="NASDAQ",
                market="Israel",
                isin="IL0010823792",
                numeric_code="-",
                theme_chip="Specialty foundry / photonics foundry",
                research_summary="Tower 更偏特色工艺、模拟和 photonics foundry，A 股主映射要偏向特色工艺与功率/模拟平台，而不是先进逻辑。",
                main_matches=[
                    _match(
                        code="688347",
                        name="华虹公司",
                        role="特色工艺/功率器件代工",
                        score=17,
                        supply_chain_position="特色工艺代工",
                        mapping_path="TSEM -> specialty foundry -> A股特色工艺代工",
                        judgement="和 Tower 的特色工艺定位最接近，是自然的主映射首选。",
                        major_risk="若市场重新只追逐先进逻辑，特色工艺平台相对收益会变弱。",
                    ),
                    _match(
                        code="688396",
                        name="华润微",
                        role="功率半导体/IDM平台",
                        score=14,
                        supply_chain_position="功率器件 / IDM",
                        mapping_path="TSEM -> analog / power process -> A股功率平台",
                        judgement="更偏功率器件与特色工艺承接，符合 Tower 的成熟工艺审美。",
                        major_risk="IDM 模式会让代工映射的纯度低于华虹。",
                    ),
                ],
                candidate_matches=[
                    _match(
                        code="688981",
                        name="中芯国际",
                        role="晶圆代工平台",
                        score=13,
                        supply_chain_position="代工平台",
                        mapping_path="TSEM -> foundry ecosystem -> A股代工平台",
                        judgement="是平台型补充，但和 Tower 的特色工艺调性并非完全同频。",
                        major_risk="先进逻辑标签更强，会稀释特色工艺映射。",
                    ),
                ],
            ),
            _stock(
                symbol="XFAB",
                display_name="X-Fab",
                company_name="X-FAB Silicon Foundries SE",
                exchange="EPA",
                market="Europe",
                isin="BE0974310428",
                numeric_code="-",
                theme_chip="Silicon photonics / specialty foundry",
                research_summary="X-Fab 兼具特色工艺与硅光 foundry 想象，A 股映射应继续放在特色工艺代工和功率平台，而不是泛设备链。",
                main_matches=[
                    _match(
                        code="688347",
                        name="华虹公司",
                        role="特色工艺代工",
                        score=17,
                        supply_chain_position="特色工艺 / 模拟代工",
                        mapping_path="XFAB -> specialty / silicon photonics foundry -> A股特色工艺",
                        judgement="与 X-Fab 的特色工艺定位高度贴近，且更有平台承接能力。",
                        major_risk="若硅光业务没有持续放量，市场仍可能按成熟制程定价。",
                    ),
                    _match(
                        code="688396",
                        name="华润微",
                        role="功率器件/IDM平台",
                        score=14,
                        supply_chain_position="功率 / 模拟平台",
                        mapping_path="XFAB -> analog / power ecosystem -> A股功率平台",
                        judgement="更偏生态补充映射，适合作为共同主映射。",
                        major_risk="IDM 业务结构和 foundry 纯度存在差异。",
                    ),
                ],
                candidate_matches=[
                    _match(
                        code="688981",
                        name="中芯国际",
                        role="晶圆代工平台",
                        score=13,
                        supply_chain_position="代工平台",
                        mapping_path="XFAB -> foundry ecosystem -> A股代工平台",
                        judgement="平台补充逻辑成立，但特色工艺直接性弱于华虹。",
                        major_risk="估值更多受先进逻辑预期影响，而非 X-Fab 式特色工艺预期。",
                    ),
                ],
            ),
        ],
    ),
    _theme(
        "先进封装 / 玻璃基板 / HBM设备",
        [
            _stock(
                symbol="TOWA",
                display_name="Towa",
                company_name="TOWA CORPORATION",
                exchange="TSE",
                market="Japan",
                isin="JP3555700008",
                numeric_code="6315",
                theme_chip="HBM packaging / advanced packaging equipment",
                research_summary="TOWA 是更典型的先进封装设备映射，A 股主映射要优先找工艺设备与测试设备，而不是只停在封装材料概念。",
                main_matches=[
                    _match(
                        code="688120",
                        name="华海清科",
                        role="先进封装/CMP设备",
                        score=16,
                        supply_chain_position="先进封装关键设备",
                        mapping_path="TOWA -> advanced packaging equipment -> A股工艺设备",
                        judgement="更靠近先进封装核心设备环节，符合 Serenity 对设备 choke point 的偏好。",
                        major_risk="先进封装设备放量仍依赖客户资本开支与验证节奏。",
                    ),
                    _match(
                        code="300604",
                        name="长川科技",
                        role="测试设备/先进封测",
                        score=14,
                        supply_chain_position="测试设备",
                        mapping_path="TOWA -> 封装测试环节 -> A股测试设备",
                        judgement="是封装链条里的关键装备，但更偏测试段，不如前者贴近主工艺设备。",
                        major_risk="订单节奏受行业资本开支波动影响较大。",
                    ),
                ],
                candidate_matches=[
                    _match(
                        code="600520",
                        name="文一科技",
                        role="封装设备",
                        score=13,
                        supply_chain_position="封装设备",
                        mapping_path="TOWA -> 封装设备 -> A股封装装备",
                        judgement="方向对，但平台能力和核心工艺代表性弱于主映射。",
                        major_risk="产品结构与验证壁垒仍需持续强化。",
                    ),
                ],
            ),
            _stock(
                symbol="LPK",
                display_name="LPKF / LPK thesis",
                company_name="LPKF Laser & Electronics SE",
                exchange="XETR",
                market="Europe",
                isin="DE0006450000",
                numeric_code="-",
                theme_chip="Glass substrates / advanced packaging",
                research_summary="这条线更偏玻璃基板和先进封装新材料，A 股映射应优先材料与玻璃基板承接者，而不是泛封装设备。",
                main_matches=[
                    _match(
                        code="603773",
                        name="沃格光电",
                        role="玻璃基板/显示与封装材料",
                        score=16,
                        supply_chain_position="玻璃基板 / 封装材料",
                        mapping_path="LPK thesis -> glass substrate -> A股玻璃基板材料",
                        judgement="是最直接的玻璃基板映射，更接近 Serenity 偏好的新材料 choke point。",
                        major_risk="新场景导入仍处于产业验证阶段，放量节奏有不确定性。",
                    ),
                    _match(
                        code="601208",
                        name="东材科技",
                        role="电子材料/封装材料",
                        score=13,
                        supply_chain_position="封装材料",
                        mapping_path="LPK thesis -> advanced packaging materials -> A股电子材料",
                        judgement="更偏材料承接层，适合作为主映射补充。",
                        major_risk="和玻璃基板的直接性弱于沃格光电。",
                    ),
                ],
                candidate_matches=[
                    _match(
                        code="002106",
                        name="莱宝高科",
                        role="玻璃基材/显示材料",
                        score=12,
                        supply_chain_position="玻璃基材",
                        mapping_path="LPK thesis -> glass-related materials -> A股玻璃材料",
                        judgement="相关性存在，但更多是玻璃材料泛映射，适合作为候选池。",
                        major_risk="与先进封装玻璃基板主线之间仍有较长映射路径。",
                    ),
                ],
            ),
        ],
    ),
    _theme(
        "商业航天 / 卫星 / 发射",
        [
            _stock(
                symbol="RKLB",
                display_name="Rocket Lab",
                company_name="Rocket Lab USA, Inc.",
                exchange="NASDAQ",
                market="US",
                isin="US7731221062",
                numeric_code="-",
                theme_chip="Launch / space systems / SpaceX #2 thesis",
                research_summary="商业航天在 A 股上的纯度不如 AI 硬件链高，需要把真正具备卫星制造和系统能力的标的放前面，其余配套放到候选池。",
                main_matches=[
                    _match(
                        code="600118",
                        name="中国卫星",
                        role="卫星制造/卫星应用",
                        score=15,
                        supply_chain_position="卫星整星 / 系统平台",
                        mapping_path="RKLB -> space systems -> A股卫星系统平台",
                        judgement="在 A 股里最接近卫星系统与整星平台能力，是较合理的主映射。",
                        major_risk="商业化节奏受体制订单与新业务推进共同影响。",
                    ),
                    _match(
                        code="600879",
                        name="航天电子",
                        role="航天电子配套",
                        score=13,
                        supply_chain_position="航天电子配套",
                        mapping_path="RKLB -> 航天电子链条 -> A股配套",
                        judgement="更偏关键配套而非整星平台，适合作为主映射补充。",
                        major_risk="弹性依赖具体配套渗透率，市场想象力弱于整星平台。",
                    ),
                ],
                candidate_matches=[
                    _match(
                        code="300762",
                        name="上海瀚讯",
                        role="卫星通信",
                        score=12,
                        supply_chain_position="卫星通信应用",
                        mapping_path="RKLB -> satellite ecosystem -> A股卫星通信",
                        judgement="属于生态受益层，不是最直接的发射与系统映射。",
                        major_risk="更偏应用和通信侧，和火箭发射主线并不完全同频。",
                    ),
                ],
            ),
            _stock(
                symbol="-",
                display_name="SpaceX",
                company_name="Space Exploration Technologies Corp.",
                exchange="Private",
                market="US",
                isin="-",
                numeric_code="-",
                theme_chip="Space / satellite / launch ecosystem",
                research_summary="Private 主题更适合作为生态映射，不应强行装作可交易可比公司；页面上要明确这是系统级映射而非可比估值映射。",
                main_matches=[
                    _match(
                        code="600118",
                        name="中国卫星",
                        role="卫星制造/卫星应用",
                        score=14,
                        supply_chain_position="卫星系统平台",
                        mapping_path="SpaceX ecosystem -> satellite systems -> A股卫星平台",
                        judgement="更适合作为生态平台映射，而非直接可比映射。",
                        major_risk="SpaceX 的发射、星链和航天系统一体化优势在 A 股中没有完全对位标的。",
                    ),
                    _match(
                        code="600879",
                        name="航天电子",
                        role="航天电子配套",
                        score=12,
                        supply_chain_position="航天电子配套",
                        mapping_path="SpaceX ecosystem -> avionics / subsystems -> A股配套",
                        judgement="偏配套层，不宜给过高 Serenity Fit。",
                        major_risk="更多是题材映射，非真正的系统平台映射。",
                    ),
                ],
                candidate_matches=[
                    _match(
                        code="300762",
                        name="上海瀚讯",
                        role="卫星通信",
                        score=11,
                        supply_chain_position="卫星通信应用",
                        mapping_path="SpaceX ecosystem -> satellite internet -> A股通信应用",
                        judgement="更偏生态受益，适合作为候选池尾部。",
                        major_risk="与发射及航天系统主线距离较远。",
                    ),
                ],
            ),
        ],
    ),
    _theme(
        "电力 / 公用事业 / 电网设备",
        [
            _stock(
                symbol="XLU",
                display_name="Utilities Select Sector SPDR",
                company_name="Utilities Select Sector SPDR Fund",
                exchange="NYSEARCA",
                market="US",
                isin="US81369Y8865",
                numeric_code="-",
                theme_chip="Utilities / AI power bottleneck / grid modernization",
                research_summary="这条线是 Serenity 非常重视的 AI power bottleneck，但 A 股映射应优先找电网自动化和关键设备，而不是泛公用事业。",
                main_matches=[
                    _match(
                        code="600406",
                        name="国电南瑞",
                        role="电网自动化/调度系统",
                        score=17,
                        supply_chain_position="电网自动化 / 调度系统",
                        mapping_path="XLU -> grid modernization -> A股电网自动化",
                        judgement="更接近电网升级中的关键中枢，符合 Serenity 对基础设施 bottleneck 的偏好。",
                        major_risk="电网投资节奏和招标周期会影响兑现速度。",
                    ),
                    _match(
                        code="000400",
                        name="许继电气",
                        role="输配电/电网设备",
                        score=15,
                        supply_chain_position="输配电关键设备",
                        mapping_path="XLU -> power equipment -> A股输配电设备",
                        judgement="比泛电力股更接近设备 choke point，适合作为主映射补充。",
                        major_risk="产品周期更受基建投资节奏影响，弹性低于纯软件中枢。",
                    ),
                ],
                candidate_matches=[
                    _match(
                        code="601179",
                        name="中国西电",
                        role="输变电设备",
                        score=13,
                        supply_chain_position="输变电设备",
                        mapping_path="XLU -> grid capex -> A股输变电设备",
                        judgement="方向正确，但更偏广谱设备供应，不是最核心自动化中枢。",
                        major_risk="设备制造属性使盈利弹性受订单结构影响较大。",
                    ),
                    _match(
                        code="300693",
                        name="盛弘股份",
                        role="电力电子/充储配电",
                        score=12,
                        supply_chain_position="电力电子 / 配电侧",
                        mapping_path="XLU -> power bottleneck -> A股配电与电力电子",
                        judgement="属于受益延伸，不宜放到主映射层。",
                        major_risk="更依赖配电与储能景气，不完全等同电网瓶颈主线。",
                    ),
                ],
            ),
        ],
    ),
    _theme(
        "关键矿物 / 稀土 / 战略材料",
        [
            _stock(
                symbol="VNP",
                display_name="5N Plus",
                company_name="5N Plus Inc.",
                exchange="TSX",
                market="Canada",
                isin="CA33833L1094",
                numeric_code="-",
                theme_chip="Critical minerals / strategic materials sovereignty",
                research_summary="战略材料是 Serenity 方法论里典型的上游 choke point 方向，A 股映射应偏资源与加工一体化，而不是泛有色主题。",
                main_matches=[
                    _match(
                        code="600111",
                        name="北方稀土",
                        role="稀土龙头/战略资源",
                        score=17,
                        supply_chain_position="关键矿物 / 稀土上游",
                        mapping_path="5N Plus -> strategic materials -> A股稀土龙头",
                        judgement="是最直接的战略资源映射，符合 Serenity 对关键矿物上游的偏好。",
                        major_risk="资源价格周期会掩盖产业链战略属性，导致估值波动较大。",
                    ),
                    _match(
                        code="600392",
                        name="盛和资源",
                        role="稀土资源与加工",
                        score=15,
                        supply_chain_position="资源 + 加工",
                        mapping_path="5N Plus -> materials sovereignty -> A股资源加工一体化",
                        judgement="资源与加工一体化更符合关键材料自主可控逻辑。",
                        major_risk="盈利对商品价格弹性较高，产业链战略叙事易被周期噪音覆盖。",
                    ),
                ],
                candidate_matches=[
                    _match(
                        code="600259",
                        name="广晟有色",
                        role="稀土与有色资源",
                        score=14,
                        supply_chain_position="有色资源",
                        mapping_path="5N Plus -> strategic materials -> A股资源平台",
                        judgement="方向一致，但和关键矿物纯主线相比更偏综合资源平台。",
                        major_risk="综合资源属性会降低单一战略材料映射纯度。",
                    ),
                ],
            ),
        ],
    ),
    _theme(
        "机器人 / 具身智能 / 核心部件",
        [
            _stock(
                symbol="VPG",
                display_name="Vishay Precision Group",
                company_name="Vishay Precision Group, Inc.",
                exchange="NYSE",
                market="US",
                isin="US92835K1034",
                numeric_code="-",
                theme_chip="Precision sensing / robotics hand / force control",
                research_summary="机器人若从演示走向复杂操作，最容易形成高附加值 choke point 的不是泛软件，而是手部、力控和高精度 sensing 这些难替代部位。",
                main_matches=[
                    _match(
                        code="301413",
                        name="安培龙",
                        role="高精度传感器",
                        score=17,
                        supply_chain_position="手部 / 力控 sensing",
                        mapping_path="VPG -> precision sensing -> A股高精度传感器",
                        judgement="最贴近 Serenity 对高附加值感知部件的审美，属于具身智能里更接近真实稀缺性的环节。",
                        major_risk="机器人相关收入占比仍需继续验证，短期可能仍被按传统传感器公司定价。",
                    ),
                    _match(
                        code="300124",
                        name="汇川技术",
                        role="运动控制 / 力控平台",
                        score=14,
                        supply_chain_position="执行链控制层",
                        mapping_path="VPG -> force sensing -> A股控制与执行平台",
                        judgement="并非同类产品，但在机器人高精度控制闭环里位置接近，属于 Serenity 方法下的系统层主映射。",
                        major_risk="平台属性强于单点感知，会弱化纯传感部件弹性。",
                    ),
                ],
                candidate_matches=[
                    _match(
                        code="603728",
                        name="鸣志电器",
                        role="步进 / 伺服执行",
                        score=13,
                        supply_chain_position="执行器 / 驱控",
                        mapping_path="VPG -> robotics control loop -> A股执行器",
                        judgement="方向相关，但更偏执行端，和精密 sensing 的对应关系次一级。",
                        major_risk="人形机器人放量节奏不确定，主题弹性高于业绩兑现。",
                    ),
                    _match(
                        code="688160",
                        name="步科股份",
                        role="控制器 / 驱控系统",
                        score=11,
                        supply_chain_position="机器人控制配套",
                        mapping_path="VPG -> robotics control chain -> A股配套控制",
                        judgement="更适合作候选池观察，贴合机器人硬件主线但非最直接的 sensing 映射。",
                        major_risk="业务面更分散，纯机器人主线映射度有限。",
                    ),
                ],
            ),
            _stock(
                symbol="AEVA",
                display_name="Aeva Technologies",
                company_name="Aeva Technologies, Inc.",
                exchange="NASDAQ",
                market="US",
                isin="US00835Q1031",
                numeric_code="-",
                theme_chip="FMCW LiDAR / physical AI sensing / robotics perception",
                research_summary="Serenity 看 AEVA，重点是机器人感知层的技术路径升级。若具身智能重视 deterministic velocity 和更高质量的感知闭环，光源、激光与光学器件链会先被重估。",
                main_matches=[
                    _match(
                        code="688167",
                        name="炬光科技",
                        role="精密激光 / 光源",
                        score=17,
                        supply_chain_position="上游激光器件",
                        mapping_path="AEVA -> FMCW LiDAR -> A股精密激光",
                        judgement="最符合 Serenity 的上游光源审美，属于感知链里更难替代的器件段。",
                        major_risk="量子与机器人感知需求仍早期，短期估值更多受其他高端制造景气影响。",
                    ),
                    _match(
                        code="301421",
                        name="波长光电",
                        role="精密光学器件",
                        score=15,
                        supply_chain_position="光学 / 感知器件",
                        mapping_path="AEVA -> perception optics -> A股精密光学",
                        judgement="更贴近光学感知路径，是 A 股里较直接的机器人感知器件映射。",
                        major_risk="机器人感知需求仍需更明确客户验证，短期更多依赖泛光学需求。",
                    ),
                ],
                candidate_matches=[
                    _match(
                        code="688307",
                        name="中润光学",
                        role="精密光学模组",
                        score=13,
                        supply_chain_position="光学成像 / 模组",
                        mapping_path="AEVA -> sensing optics -> A股光学模组",
                        judgement="与机器人感知方向相关，但更偏模组集成而非上游光源 choke point。",
                        major_risk="模组属性会降低稀缺性溢价。",
                    ),
                    _match(
                        code="688002",
                        name="睿创微纳",
                        role="高端感知芯片",
                        score=12,
                        supply_chain_position="感知芯片 / 传感",
                        mapping_path="AEVA -> physical AI sensing -> A股高端感知",
                        judgement="感知链方向正确，但与 FMCW LiDAR 的工艺路径并不完全一致，更适合作观察候选。",
                        major_risk="主业与机器人 LiDAR 并非同一条技术路径，映射存在偏移。",
                    ),
                ],
            ),
            _stock(
                symbol="SSYS",
                display_name="Stratasys",
                company_name="Stratasys Ltd.",
                exchange="NASDAQ",
                market="US/Israel",
                isin="IL0011267213",
                numeric_code="-",
                theme_chip="Humanoid skeleton / 3D printing materials / structure",
                research_summary="机器人从样机走向量产，结构件和制造路径会开始决定成本、轻量化和认证速度。Serenity 看 SSYS，本质上是在押结构件与先进制造工艺的前置卡位。",
                main_matches=[
                    _match(
                        code="688333",
                        name="铂力特",
                        role="金属3D打印",
                        score=17,
                        supply_chain_position="结构制造 / 增材",
                        mapping_path="SSYS -> humanoid frame -> A股金属增材制造",
                        judgement="是最直接的机器人骨架与先进制造映射，符合 Serenity 对制造 choke point 的方法。",
                        major_risk="机器人结构件需求的真实放量仍需验证，短期仍由航空航天等下游驱动。",
                    ),
                    _match(
                        code="300580",
                        name="贝斯特",
                        role="精密结构件",
                        score=14,
                        supply_chain_position="结构件 / 精密制造",
                        mapping_path="SSYS -> robotics structure -> A股精密结构制造",
                        judgement="更接近机器人结构和复杂制造的现实承接者，属于方法论上的主映射。",
                        major_risk="业务口径更广，机器人纯度不如增材制造路径。",
                    ),
                ],
                candidate_matches=[
                    _match(
                        code="002747",
                        name="埃斯顿",
                        role="机器人本体 / 控制",
                        score=13,
                        supply_chain_position="机器人本体",
                        mapping_path="SSYS -> humanoid expansion -> A股本体制造",
                        judgement="是机器人主线的高认知度标的，但与骨架制造路径的对应关系更偏扩散映射。",
                        major_risk="本体竞争激烈，估值受主题情绪影响较大。",
                    ),
                    _match(
                        code="603667",
                        name="五洲新春",
                        role="轴承 / 机械部件",
                        score=11,
                        supply_chain_position="机械部件配套",
                        mapping_path="SSYS -> robotics structure -> A股机械配套",
                        judgement="作为候选池可观察机器人机械零部件扩散，但不属于最核心的结构制造 choke point。",
                        major_risk="机器人业务占比和客户验证都还不够清晰。",
                    ),
                ],
            ),
        ],
    ),
    _theme(
        "量子计算 / 精密制造 / 上游设备",
        [
            _stock(
                symbol="INFQ",
                display_name="Infleqtion",
                company_name="Infleqtion, Inc.",
                exchange="Private/Public tracking",
                market="US",
                isin="-",
                numeric_code="-",
                theme_chip="Neutral-atom quantum computing / quantum sensing",
                research_summary="量子计算主题采用纯设备链口径，不做泛量子概念。INFQ 的看点在于它不只是 science project，而是已经有量子 sensing 和更接近商业化的设备验证路径。",
                main_matches=[
                    _match(
                        code="688027",
                        name="国盾量子",
                        role="量子硬件 / 系统",
                        score=17,
                        supply_chain_position="量子系统锚点",
                        mapping_path="INFQ -> quantum hardware -> A股量子系统",
                        judgement="是 A 股里最接近量子硬件与系统层的直接映射，适合作为核心主映射。",
                        major_risk="业务口径更广且 A 股量子交易噪音大，容易被泛概念扰动。",
                    ),
                    _match(
                        code="688167",
                        name="炬光科技",
                        role="精密激光 / 光源器件",
                        score=15,
                        supply_chain_position="量子设备上游光源",
                        mapping_path="INFQ -> quantum sensing optics -> A股精密激光",
                        judgement="量子 sensing 与冷原子路径都离不开高质量光源，是更符合 Serenity 审美的上游硬件映射。",
                        major_risk="量子需求占比小，短期验证仍偏间接。",
                    ),
                ],
                candidate_matches=[
                    _match(
                        code="301421",
                        name="波长光电",
                        role="精密光学器件",
                        score=13,
                        supply_chain_position="光学链配套",
                        mapping_path="INFQ -> quantum optics -> A股精密光学",
                        judgement="方向正确但更偏器件配套，适合做候选池观察。",
                        major_risk="和量子计算的直接收入关系仍需验证。",
                    ),
                    _match(
                        code="002158",
                        name="汉钟精机",
                        role="真空基础设备",
                        score=12,
                        supply_chain_position="设备基础设施",
                        mapping_path="INFQ -> quantum equipment chain -> A股真空设备",
                        judgement="符合 Serenity 的上游设备方法，但属于方法论映射，不是纯业务映射。",
                        major_risk="真空设备与量子业务之间的传导链条较长。",
                    ),
                ],
            ),
            _stock(
                symbol="ALRIB",
                display_name="AlixaR / Riber",
                company_name="Riber SA",
                exchange="EPA",
                market="France",
                isin="FR0000075954",
                numeric_code="-",
                theme_chip="MBE / quantum dot fabrication / precision manufacturing",
                research_summary="ALRIB 对应的是量子器件前段工艺和 MBE 设备，不是应用端热闹概念。真正符合 Serenity 方法的是去找量子器件若要放量，谁会先在前段精密制造里卡位。",
                main_matches=[
                    _match(
                        code="688012",
                        name="中微公司",
                        role="高端精密设备",
                        score=16,
                        supply_chain_position="前段制造设备",
                        mapping_path="ALRIB -> MBE / fabrication equipment -> A股高端设备",
                        judgement="A 股里最接近前段精密制造设备平台的主映射，更符合 Serenity 的设备链方法。",
                        major_risk="并非 MBE 直系可比，更多是工艺设备方法论映射。",
                    ),
                    _match(
                        code="300316",
                        name="晶盛机电",
                        role="精密制造装备",
                        score=14,
                        supply_chain_position="高端制造装备",
                        mapping_path="ALRIB -> quantum fabrication -> A股精密装备",
                        judgement="适合作为量子前段工艺设备的核心受益样本之一，但映射更偏制造平台。",
                        major_risk="主营与量子器件非同一赛道，映射需要依赖方法论理解。",
                    ),
                ],
                candidate_matches=[
                    _match(
                        code="002008",
                        name="大族激光",
                        role="激光精密加工设备",
                        score=13,
                        supply_chain_position="精密加工",
                        mapping_path="ALRIB -> precision fabrication -> A股激光加工设备",
                        judgement="能体现量子器件制造里的精密加工逻辑，但更适合候选池层。",
                        major_risk="业务广谱化较强，纯量子映射度有限。",
                    ),
                    _match(
                        code="688120",
                        name="华海清科",
                        role="精密工艺设备",
                        score=12,
                        supply_chain_position="工艺设备",
                        mapping_path="ALRIB -> precision process -> A股高端工艺装备",
                        judgement="符合上游设备方法，但不是量子制造最直接的一层，适合做候选观察。",
                        major_risk="量子映射为方法论延展，短期难以体现在业绩端。",
                    ),
                ],
            ),
        ],
    ),
]


def get_a_share_match_catalog() -> dict[str, Any]:
    total_project_stocks = sum(theme["project_stock_count"] for theme in _THEMES)
    total_related_stocks = sum(theme["related_stock_count"] for theme in _THEMES)
    return {
        "title": "Serenity推荐股与A股映射表",
        "eyebrow": "",
        "description": (
            "基于 Serenity 的上游瓶颈、供应链映射和前瞻错配框架，对项目推荐股做 A 股主映射与候选池重排。"
            " 页面保留行情与 Tweets 研究能力，同时把原有静态标签升级为可比较的 Serenity Fit 评分卡。"
        ),
        "theme_count": len(_THEMES),
        "project_stock_count": total_project_stocks,
        "theme_related_stock_count": total_related_stocks,
        "themes": _THEMES,
    }


def get_theme_a_share_index(theme_slug: str) -> dict[str, Any] | None:
    normalized_slug = str(theme_slug or "").strip()
    if not normalized_slug:
        return None
    for theme in _THEMES:
        if str(theme.get("slug") or "").strip() == normalized_slug:
            return theme.get("a_share_index") or None
    return None


def _normalize_history_row(row: Any) -> dict[str, Any] | None:
    if isinstance(row, dict):
        raw_date = row.get("date")
        open_value = row.get("open")
        high_value = row.get("high")
        low_value = row.get("low")
        close_value = row.get("close")
    else:
        raw_date = getattr(row, "date", None)
        open_value = getattr(row, "open", None)
        high_value = getattr(row, "high", None)
        low_value = getattr(row, "low", None)
        close_value = getattr(row, "close", None)

    if raw_date is None or close_value in (None, ""):
        return None
    if hasattr(raw_date, "to_pydatetime"):
        raw_date = raw_date.to_pydatetime()
    if isinstance(raw_date, dt.datetime):
        date_text = raw_date.date().isoformat()
    elif isinstance(raw_date, dt.date):
        date_text = raw_date.isoformat()
    else:
        date_text = str(raw_date).strip()[:10]
    try:
        open_number = float(open_value if open_value not in (None, "") else close_value)
        high_number = float(high_value if high_value not in (None, "") else close_value)
        low_number = float(low_value if low_value not in (None, "") else close_value)
        close_number = float(close_value)
    except (TypeError, ValueError):
        return None
    if not date_text or close_number <= 0:
        return None
    return {
        "date": date_text,
        "open": open_number,
        "high": high_number,
        "low": low_number,
        "close": close_number,
    }


def _normalize_history_rows(rows: Any) -> list[dict[str, Any]]:
    if rows is None:
        return []
    normalized_rows: list[dict[str, Any]] = []
    iterator = rows.to_dict("records") if hasattr(rows, "to_dict") else rows
    for row in iterator or []:
        item = _normalize_history_row(row)
        if item:
            normalized_rows.append(item)
    normalized_rows.sort(key=lambda item: str(item.get("date") or ""))
    return normalized_rows


def _normalize_theme_index_db_rows(rows: Any) -> list[dict[str, Any]]:
    normalized_rows: list[dict[str, Any]] = []
    for row in rows or []:
        raw_dt = getattr(row, "dt", None)
        raw_open = getattr(row, "o", None)
        raw_high = getattr(row, "h", None)
        raw_low = getattr(row, "l", None)
        raw_close = getattr(row, "c", None)
        item = _normalize_history_row(
            {
                "date": raw_dt,
                "open": raw_open,
                "high": raw_high,
                "low": raw_low,
                "close": raw_close,
            }
        )
        if item:
            normalized_rows.append(item)
    normalized_rows.sort(key=lambda item: str(item.get("date") or ""))
    return normalized_rows


def _merge_theme_index_history_rows(*row_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for rows in row_groups:
        for row in rows or []:
            date_text = str(row.get("date") or "").strip()
            if date_text:
                merged[date_text] = dict(row)
    return [merged[key] for key in sorted(merged.keys())]


def _theme_index_full_history_cache_key(code: str) -> str:
    return f"a_share_matches:theme_index:full_history:{normalize_a_share_code(code)}:d"


def _query_theme_index_klines_from_db(code: str) -> list[dict[str, Any]]:
    normalized_code = normalize_a_share_code(code)
    try:
        rows = db.klines_query(
            market=Market.A.value,
            code=normalized_code,
            frequency="d",
            limit=None,
            order="asc",
        )
    except Exception:
        return []
    return _normalize_theme_index_db_rows(rows)


def _persist_theme_index_klines_to_db(code: str, rows: list[dict[str, Any]]) -> None:
    normalized_rows = _normalize_history_rows(rows)
    if not normalized_rows:
        return
    dataframe = pd.DataFrame(
        [
            {
                "date": dt.datetime.fromisoformat(str(row["date"])),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row.get("volume") or 0.0),
            }
            for row in normalized_rows
        ]
    )
    if dataframe.empty:
        return
    db.klines_insert(
        market=Market.A.value,
        code=normalize_a_share_code(code),
        frequency="d",
        klines=dataframe,
    )


def _fetch_theme_index_klines_from_exchange(
    code: str,
    lookback_days: int | None,
    range_mode: str = "",
    force_full_history: bool = False,
) -> list[dict[str, Any]]:
    normalized_range_mode = str(range_mode or "").strip().lower()
    is_max_range = force_full_history or normalized_range_mode in {"max", "all"}
    if is_max_range:
        pages = 60
    else:
        requested_days = max(int(lookback_days or 20), 20)
        pages = max(1, min(6, int(requested_days / 120) + 1))
    ex = get_exchange(Market.A)
    dataframe = ex.klines(normalize_a_share_code(code), "d", args={"pages": pages})
    return _normalize_history_rows(dataframe)


def _load_theme_index_constituent_history(
    code: str,
    lookback_days: int | None,
    range_mode: str = "",
) -> list[dict[str, Any]]:
    normalized_range_mode = str(range_mode or "").strip().lower()
    is_max_range = normalized_range_mode in {"max", "all"}
    requested_days = None if is_max_range else max(int(lookback_days or 20), 1)
    persisted_rows = _query_theme_index_klines_from_db(code)

    full_history_marker = {}
    try:
        full_history_marker = db.cache_get(_theme_index_full_history_cache_key(code)) or {}
    except Exception:
        full_history_marker = {}
    has_full_history = bool(full_history_marker.get("full_history"))

    latest_cached_text = ""
    try:
        latest_cached_text = str(db.klines_last_datetime(Market.A.value, normalize_a_share_code(code), "d") or "")
    except Exception:
        latest_cached_text = str(persisted_rows[-1]["date"] if persisted_rows else "")
    latest_cached_text = latest_cached_text[:10]

    should_force_full_history = is_max_range and (not persisted_rows or not has_full_history)
    needs_incremental_refresh = False
    if persisted_rows:
        latest_row_date = str(persisted_rows[-1].get("date") or "")
        if latest_cached_text and latest_cached_text > latest_row_date:
            latest_row_date = latest_cached_text
        today_text = dt.date.today().isoformat()
        if latest_row_date < today_text:
            needs_incremental_refresh = True
    else:
        needs_incremental_refresh = True

    if requested_days is not None and len(persisted_rows) < requested_days:
        needs_incremental_refresh = True

    fetched_rows: list[dict[str, Any]] = []
    if should_force_full_history or needs_incremental_refresh:
        try:
            fetched_rows = _fetch_theme_index_klines_from_exchange(
                code,
                lookback_days=lookback_days,
                range_mode=range_mode,
                force_full_history=should_force_full_history,
            )
        except Exception:
            fetched_rows = []
        if latest_cached_text:
            fetched_rows = [
                row for row in fetched_rows if str(row.get("date") or "") > latest_cached_text
            ] if not should_force_full_history else fetched_rows
        if fetched_rows:
            try:
                _persist_theme_index_klines_to_db(code, fetched_rows)
            except Exception:
                pass
            persisted_rows = _merge_theme_index_history_rows(persisted_rows, fetched_rows)
        if should_force_full_history and (persisted_rows or fetched_rows):
            try:
                db.cache_set(
                    _theme_index_full_history_cache_key(code),
                    {"full_history": True, "updated_at": dt.date.today().isoformat()},
                    expire=0,
                )
            except Exception:
                pass

    if requested_days is not None:
        return persisted_rows[-requested_days:]
    return persisted_rows


def build_theme_index_history_series(
    index_meta: dict[str, Any],
    histories: dict[str, Any],
    range_mode: str = "",
    lookback_days: int | None = None,
    reference_date: str = "",
    reference_closes: dict[str, float] | None = None,
) -> dict[str, Any]:
    base_value = float(index_meta.get("base_value") or 1000.0)
    constituents = list(index_meta.get("constituents") or [])
    normalized_range_mode = str(range_mode or "").strip().lower()
    is_max_range = normalized_range_mode in {"max", "all"}
    lookback_label = "最长历史" if is_max_range else f"近{int(lookback_days or 20)}日"
    normalized_histories = {
        str(code or "").strip(): _normalize_history_rows(rows)
        for code, rows in (histories or {}).items()
    }

    used_constituents: list[dict[str, Any]] = []
    common_dates: set[str] | None = None
    row_maps: dict[str, dict[str, dict[str, Any]]] = {}
    for item in constituents:
        code = str(item.get("code") or "").strip()
        rows = normalized_histories.get(code) or []
        if not rows:
            continue
        row_map = {str(row.get("date") or ""): row for row in rows if row.get("date")}
        if not row_map:
            continue
        row_maps[code] = row_map
        used_constituents.append(item)
        date_set = set(row_map.keys())
        common_dates = date_set if common_dates is None else (common_dates & date_set)

    ordered_dates = sorted(common_dates or [])
    if not used_constituents or not ordered_dates:
        return {
            "theme_slug": str(index_meta.get("slug") or ""),
            "title": str(index_meta.get("chart_title") or index_meta.get("name") or ""),
            "base_value": base_value,
            "lookback_label": lookback_label,
            "is_max_range": is_max_range,
            "coverage": {
                "used_constituents": len(used_constituents),
                "total_constituents": len(constituents),
                "date_points": 0,
            },
            "constituents": constituents,
            "series": [],
        }

    total_weight = sum(float(item.get("weight") or 0.0) for item in used_constituents) or 1.0
    effective_reference_date = str(reference_date or ordered_dates[0])
    normalized_reference_closes = {
        str(code or ""): float(value)
        for code, value in dict(reference_closes or {}).items()
        if str(code or "")
    }
    if not normalized_reference_closes:
        normalized_reference_closes = {
            str(item.get("code") or ""): float(row_maps[str(item.get("code") or "")][effective_reference_date]["close"])
            for item in used_constituents
            if effective_reference_date in row_maps.get(str(item.get("code") or ""), {})
        }

    series: list[dict[str, Any]] = []
    for date_text in ordered_dates:
        weighted_values = {"open": 0.0, "high": 0.0, "low": 0.0, "close": 0.0}
        for item in used_constituents:
            code = str(item.get("code") or "")
            weight = float(item.get("weight") or 0.0)
            base_close = float(normalized_reference_closes.get(code) or 0.0)
            row = row_maps[code][date_text]
            if base_close <= 0 or weight <= 0:
                continue
            for field_name in ("open", "high", "low", "close"):
                weighted_values[field_name] += ((float(row[field_name]) / base_close) - 1.0) * weight
        series.append(
            {
                "date": date_text,
                "open": round(base_value * (1.0 + weighted_values["open"] / total_weight), 4),
                "high": round(base_value * (1.0 + weighted_values["high"] / total_weight), 4),
                "low": round(base_value * (1.0 + weighted_values["low"] / total_weight), 4),
                "close": round(base_value * (1.0 + weighted_values["close"] / total_weight), 4),
            }
        )

    return {
        "theme_slug": str(index_meta.get("slug") or ""),
        "title": str(index_meta.get("chart_title") or index_meta.get("name") or ""),
        "base_value": base_value,
        "reference_date": effective_reference_date,
        "lookback_label": lookback_label,
        "is_max_range": is_max_range,
        "coverage": {
            "used_constituents": len(used_constituents),
            "total_constituents": len(constituents),
            "date_points": len(series),
        },
        "constituents": constituents,
        "series": series,
    }


def build_theme_index_reference_closes(
    index_meta: dict[str, Any],
    histories: dict[str, Any],
    reference_date: str = "",
) -> tuple[str, dict[str, float]]:
    constituents = list(index_meta.get("constituents") or [])
    normalized_histories = {
        str(code or "").strip(): _normalize_history_rows(rows)
        for code, rows in (histories or {}).items()
    }
    common_dates: set[str] | None = None
    row_maps: dict[str, dict[str, dict[str, Any]]] = {}
    for item in constituents:
        code = str(item.get("code") or "").strip()
        rows = normalized_histories.get(code) or []
        if not rows:
            continue
        row_map = {str(row.get("date") or ""): row for row in rows if row.get("date")}
        if not row_map:
            continue
        row_maps[code] = row_map
        date_set = set(row_map.keys())
        common_dates = date_set if common_dates is None else (common_dates & date_set)
    ordered_dates = sorted(common_dates or [])
    if not ordered_dates:
        return "", {}
    requested_reference_date = str(reference_date or "").strip()
    reference_date = requested_reference_date if requested_reference_date in ordered_dates else ordered_dates[0]
    reference_closes = {
        str(item.get("code") or ""): float(row_maps[str(item.get("code") or "")][reference_date]["close"])
        for item in constituents
        if str(item.get("code") or "") in row_maps and reference_date in row_maps[str(item.get("code") or "")]
    }
    return reference_date, reference_closes


def build_theme_index_live_snapshot(
    index_meta: dict[str, Any],
    tick_map: dict[str, Any],
    reference_closes: dict[str, float],
    as_of_date: str | None = None,
) -> dict[str, Any]:
    base_value = float(index_meta.get("base_value") or 1000.0)
    total_weight = 0.0
    weighted_rate = 0.0
    weighted_daily_rate = 0.0
    weighted_daily_amplitude = 0.0
    used_constituents = 0
    for item in list(index_meta.get("constituents") or []):
        code = str(item.get("code") or "").strip()
        tick = (tick_map or {}).get(code) or {}
        price = tick.get("price")
        reference_close = float((reference_closes or {}).get(code) or 0.0)
        try:
            price_value = float(price)
            weight_value = float(item.get("weight") or 0.0)
        except (TypeError, ValueError):
            continue
        if weight_value <= 0 or reference_close <= 0 or price_value <= 0:
            continue
        total_weight += weight_value
        weighted_rate += (((price_value / reference_close) - 1.0) * 100.0) * weight_value
        weighted_daily_rate += float(tick.get("rate") or 0.0) * weight_value
        weighted_daily_amplitude += float(tick.get("swing_rate") or 0.0) * weight_value
        used_constituents += 1
    raw_change_pct = (weighted_rate / total_weight) if total_weight > 0 else 0.0
    change_pct = round(raw_change_pct, 4)
    index_value = round(base_value * (1.0 + change_pct / 100.0), 4)
    daily_change_pct = round((weighted_daily_rate / total_weight), 4) if total_weight > 0 else 0.0
    daily_amplitude_pct = round((weighted_daily_amplitude / total_weight), 4) if total_weight > 0 else 0.0
    snapshot_date = str(as_of_date or dt.date.today().isoformat())
    return {
        "date": snapshot_date,
        "change_pct": change_pct,
        "index_value": index_value,
        "daily_change_pct": daily_change_pct,
        "daily_amplitude_pct": daily_amplitude_pct,
        "used_constituents": used_constituents,
    }


def merge_theme_index_live_snapshot(history_result: dict[str, Any], live_snapshot: dict[str, Any] | None) -> dict[str, Any]:
    result = dict(history_result or {})
    series = [dict(item) for item in list(result.get("series") or [])]
    if not live_snapshot or not live_snapshot.get("date"):
        result["series"] = series
        result["live_index"] = live_snapshot or {}
        return result

    live_date = str(live_snapshot.get("date") or "")
    live_value = float(live_snapshot.get("index_value") or 0.0)
    if live_value <= 0:
        result["series"] = series
        result["live_index"] = live_snapshot
        return result

    if series and str(series[-1].get("date") or "") == live_date:
        last_point = dict(series[-1])
        last_point["close"] = round(live_value, 4)
        last_point["high"] = round(max(float(last_point.get("high") or live_value), live_value), 4)
        last_point["low"] = round(min(float(last_point.get("low") or live_value), live_value), 4)
        series[-1] = last_point
    else:
        previous_close = float(series[-1].get("close") or live_value) if series else live_value
        series.append(
            {
                "date": live_date,
                "open": round(previous_close, 4),
                "high": round(max(previous_close, live_value), 4),
                "low": round(min(previous_close, live_value), 4),
                "close": round(live_value, 4),
            }
        )

    result["series"] = series
    result["live_index"] = live_snapshot
    if "coverage" in result and isinstance(result["coverage"], dict):
        result["coverage"] = {
            **result["coverage"],
            "date_points": len(series),
            "live_used_constituents": int(live_snapshot.get("used_constituents") or 0),
        }
    return result


def _empty_theme_index_performance_metrics() -> dict[str, Any]:
    return {
        "daily_change_pct": None,
        "daily_amplitude_pct": None,
        "ytd_change_pct": None,
        "ytd_amplitude_pct": None,
        "year_start_date": "",
        "year_high": None,
        "year_low": None,
    }


def _build_theme_index_performance_metrics(
    series: list[dict[str, Any]] | None,
    live_index: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metrics = _empty_theme_index_performance_metrics()
    normalized_series = [dict(item) for item in list(series or []) if str(item.get("date") or "").strip()]
    normalized_live_index = dict(live_index or {})

    daily_change_pct = normalized_live_index.get("daily_change_pct")
    daily_amplitude_pct = normalized_live_index.get("daily_amplitude_pct")
    if daily_change_pct is not None:
        metrics["daily_change_pct"] = round(float(daily_change_pct), 4)
    if daily_amplitude_pct is not None:
        metrics["daily_amplitude_pct"] = round(float(daily_amplitude_pct), 4)

    latest_date_text = str(normalized_live_index.get("date") or (normalized_series[-1].get("date") if normalized_series else "")).strip()
    latest_close = float(normalized_live_index.get("index_value") or 0.0)
    if latest_close <= 0 and normalized_series:
        latest_close = float(normalized_series[-1].get("close") or 0.0)
    if not latest_date_text or latest_close <= 0:
        return metrics

    latest_year = latest_date_text[:4]
    if len(latest_year) != 4 or not latest_year.isdigit():
        return metrics

    current_year_points = [item for item in normalized_series if str(item.get("date") or "").startswith(f"{latest_year}-")]
    if not current_year_points:
        return metrics

    year_start_point = current_year_points[0]
    year_start_close = float(year_start_point.get("close") or 0.0)
    if year_start_close <= 0:
        return metrics

    year_high_values = [float(item.get("high") or item.get("close") or 0.0) for item in current_year_points]
    year_low_values = [float(item.get("low") or item.get("close") or 0.0) for item in current_year_points]
    if latest_date_text.startswith(f"{latest_year}-") and latest_close > 0:
        year_high_values.append(float(normalized_live_index.get("high") or latest_close))
        year_low_values.append(float(normalized_live_index.get("low") or latest_close))

    year_high = max(value for value in year_high_values if value > 0)
    year_low = min(value for value in year_low_values if value > 0)
    metrics["year_start_date"] = str(year_start_point.get("date") or "")
    metrics["year_high"] = round(year_high, 4)
    metrics["year_low"] = round(year_low, 4)
    metrics["ytd_change_pct"] = round(((latest_close / year_start_close) - 1.0) * 100.0, 4)
    metrics["ytd_amplitude_pct"] = round(((year_high - year_low) / year_start_close) * 100.0, 4)
    return metrics


def _load_theme_index_live_snapshot(
    index_meta: dict[str, Any],
    reference_closes: dict[str, float] | None = None,
) -> dict[str, Any]:
    effective_reference_closes = dict(reference_closes or {})
    if not effective_reference_closes:
        _, effective_reference_closes = _load_theme_index_reference_state(index_meta)
    ex = get_exchange(Market.A)
    codes = [normalize_a_share_code(str(item.get("code") or "").strip()) for item in list(index_meta.get("constituents") or []) if str(item.get("code") or "").strip()]
    normalized_ticks = fetch_tick_snapshots(ex, codes)
    tick_map: dict[str, Any] = {}
    for item in list(index_meta.get("constituents") or []):
        raw_code = str(item.get("code") or "").strip()
        normalized_code = normalize_a_share_code(raw_code)
        tick = normalized_ticks.get(normalized_code) or normalized_ticks.get(raw_code)
        if tick:
            tick_map[raw_code] = tick
    return build_theme_index_live_snapshot(index_meta, tick_map, effective_reference_closes)


def _load_theme_index_reference_state(index_meta: dict[str, Any], reference_date: str = "") -> tuple[str, dict[str, float]]:
    theme_slug = str(index_meta.get("slug") or "").strip()
    normalized_reference_date = str(reference_date or "").strip()
    if not normalized_reference_date and theme_slug and theme_slug in _THEME_INDEX_REFERENCE_STATE_CACHE:
        cached_date, cached_closes = _THEME_INDEX_REFERENCE_STATE_CACHE[theme_slug]
        return cached_date, dict(cached_closes)
    histories = _load_theme_index_constituent_histories(index_meta, None, range_mode="max")
    resolved_reference_date, reference_closes = build_theme_index_reference_closes(
        index_meta,
        histories,
        reference_date=normalized_reference_date,
    )
    if not normalized_reference_date and theme_slug and resolved_reference_date and reference_closes:
        _THEME_INDEX_REFERENCE_STATE_CACHE[theme_slug] = (resolved_reference_date, dict(reference_closes))
    return resolved_reference_date, reference_closes


def build_theme_index_live(theme_slug: str, reference_date: str = "") -> dict[str, Any]:
    index_meta = get_theme_a_share_index(theme_slug)
    if not index_meta:
        return {
            "theme_slug": str(theme_slug or ""),
            "base_value": 1000.0,
            "reference_date": "",
            "live_index": {},
            "metrics": _empty_theme_index_performance_metrics(),
            "error": "theme_not_found",
        }
    resolved_reference_date, reference_closes = _load_theme_index_reference_state(index_meta, reference_date=reference_date)
    histories = _load_theme_index_constituent_histories(index_meta, None, range_mode="max")
    history_result = build_theme_index_history_series(
        index_meta,
        histories,
        range_mode="max",
        reference_date=resolved_reference_date,
        reference_closes=reference_closes,
    )
    live_index = _load_theme_index_live_snapshot(index_meta, reference_closes=reference_closes)
    merged_result = merge_theme_index_live_snapshot(history_result, live_index)
    return {
        "theme_slug": str(index_meta.get("slug") or theme_slug or ""),
        "base_value": float(index_meta.get("base_value") or 1000.0),
        "reference_date": resolved_reference_date,
        "live_index": live_index,
        "metrics": _build_theme_index_performance_metrics(merged_result.get("series"), live_index),
        "error": "" if live_index else "live_unavailable",
    }


def _load_theme_index_constituent_histories(
    index_meta: dict[str, Any],
    lookback_days: int | None,
    range_mode: str = "",
) -> dict[str, list[dict[str, Any]]]:
    histories: dict[str, list[dict[str, Any]]] = {}
    for item in list(index_meta.get("constituents") or []):
        code = str(item.get("code") or "").strip()
        if not code:
            continue
        try:
            rows = _load_theme_index_constituent_history(
                code,
                lookback_days=lookback_days,
                range_mode=range_mode,
            )
            if rows:
                histories[code] = rows
        except Exception:
            continue
    return histories


def build_theme_index_history(
    theme_slug: str,
    lookback_days: int | None = 20,
    range_mode: str = "",
    reference_date: str = "",
) -> dict[str, Any]:
    normalized_range_mode = str(range_mode or "").strip().lower()
    is_max_range = normalized_range_mode in {"max", "all"}
    index_meta = get_theme_a_share_index(theme_slug)
    if not index_meta:
        return {
            "theme_slug": str(theme_slug or ""),
            "title": "",
            "base_value": 1000.0,
            "lookback_label": "最长历史" if is_max_range else f"近{int(lookback_days or 20)}日",
            "is_max_range": is_max_range,
            "coverage": {"used_constituents": 0, "total_constituents": 0, "date_points": 0},
            "constituents": [],
            "series": [],
        }
    normalized_lookback_days = None if is_max_range else max(int(lookback_days or 20), 1)
    resolved_reference_date, reference_closes = _load_theme_index_reference_state(index_meta, reference_date=reference_date)
    histories = _load_theme_index_constituent_histories(index_meta, normalized_lookback_days, range_mode=normalized_range_mode)
    history_result = build_theme_index_history_series(
        index_meta,
        histories,
        range_mode=normalized_range_mode,
        lookback_days=normalized_lookback_days,
        reference_date=resolved_reference_date,
        reference_closes=reference_closes,
    )
    try:
        live_snapshot = _load_theme_index_live_snapshot(index_meta, reference_closes=reference_closes)
    except Exception:
        live_snapshot = {}
    merged_result = merge_theme_index_live_snapshot(history_result, live_snapshot)
    merged_result["metrics"] = _build_theme_index_performance_metrics(merged_result.get("series"), live_snapshot)
    return merged_result
