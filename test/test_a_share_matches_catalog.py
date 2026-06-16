from pathlib import Path
import sys

from jinja2 import Environment, FileSystemLoader, select_autoescape


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "web" / "chanlun_chart"))

from cl_app.a_share_matches_catalog import get_a_share_match_catalog
from cl_app.a_share_matches_quotes import infer_project_chart_target
from cl_app.a_share_matches_tweet_notes import get_project_tweet_note
from cl_app.a_share_matches_tweets import build_tweet_detail_url


def _render_a_share_matches_template():
    template_dir = PROJECT_ROOT / "web" / "chanlun_chart" / "cl_app" / "templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("a_share_matches.html")
    catalog = get_a_share_match_catalog()
    for theme in catalog["themes"]:
      for stock in theme["project_stocks"]:
        stock["tweet_detail_url"] = build_tweet_detail_url(
            symbol=stock["symbol"],
            company_name=stock["company_name"],
            exchange=stock["exchange"],
            market=stock["market"],
            display_name=stock["display_name"],
        )
        chart_target = infer_project_chart_target(
            symbol=stock["symbol"],
            exchange=stock["exchange"],
            market_text=stock["market"],
            company_name=stock["company_name"],
        )
        stock["chart_url"] = (
            f"/?market={chart_target['market']}&code={chart_target['code']}"
            "&embedded=1&lite_chart=1&default_interval=1D&load_last_chart=0"
            if chart_target.get("market") and chart_target.get("code")
            else ""
        )
        stock["chart_unavailable_reason"] = chart_target.get("unavailable_reason", "")
        stock["chart_frequency_label"] = "主页图形"
      for related in theme["theme_related_stocks"]:
        related.setdefault("detail_url", f"/a_share_matches/theme-stock/{theme['slug']}/{related['code']}")
    return template.render(catalog=catalog)


def _render_theme_related_detail_template(context):
    template_dir = PROJECT_ROOT / "web" / "chanlun_chart" / "cl_app" / "templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("a_share_match_theme_stock.html")
    return template.render(**context)


def test_a_share_match_catalog_has_expected_structure():
    catalog = get_a_share_match_catalog()

    assert catalog["theme_count"] == len(catalog["themes"])
    assert catalog["theme_count"] == 13
    assert catalog["project_stock_count"] == 27
    assert catalog["theme_related_stock_count"] > 0

    theme_slugs = set()
    theme_titles = {theme["title"] for theme in catalog["themes"]}
    assert "AI稀有金属 / 关键矿物 / 上游资源" in theme_titles
    assert "机器人 / 具身智能 / 核心部件" in theme_titles
    assert "量子计算 / 精密制造 / 上游设备" in theme_titles

    for theme in catalog["themes"]:
        assert theme["title"]
        assert theme["slug"] not in theme_slugs
        theme_slugs.add(theme["slug"])
        assert theme["accent"]
        assert "a_share_index" in theme
        assert theme["a_share_index"]["name"].endswith("A股指数")
        assert theme["a_share_index"]["slug"] == theme["slug"]
        assert theme["a_share_index"]["chart_title"].endswith("历史价格图")
        assert theme["a_share_index"]["default_lookback_days"] == "max"
        assert theme["a_share_index"]["sample_count"] > 0
        assert theme["a_share_index"]["base_value"] == 1000.0
        assert theme["a_share_index"]["constituents"]
        assert theme["project_stock_count"] == len(theme["project_stocks"])
        assert theme["related_stock_count"] == len(theme["theme_related_stocks"])
        assert theme["project_stocks"]
        assert theme["theme_related_stocks"]

        for item in theme["a_share_index"]["constituents"]:
            assert len(item["code"]) == 6
            assert item["weight"] > 0
            assert item["source_type"] in {"main_match", "candidate_match", "theme_related"}

        for stock in theme["project_stocks"]:
            assert stock["symbol"] is not None
            assert stock["display_name"]
            assert stock["company_name"]
            assert stock["theme_chip"]
            assert stock["research_summary"]
            assert stock["serenity_reason_summary"]
            assert stock["tweet_detail_label"]
            assert stock["analysis_detail_label"] == "查看个股分析"
            assert stock["analysis_detail_url"].startswith("/a_share_matches/stock-analysis/project/")
            assert "financial_summary_short" in stock
            assert "analysis_source_label" in stock
            assert "source_validation" in stock
            assert stock["selection_reason"]["summary"]
            assert stock["selection_reason"]["fit_basis"]
            assert stock["scarcity_view"]["label"]
            assert stock["scarcity_view"]["detail"]
            assert stock["capacity_view"]["label"]
            assert stock["capacity_view"]["detail"]
            assert stock["pricing_view"]["label"]
            assert stock["pricing_view"]["detail"]
            assert stock["market_cap_research"]["current_text"]
            assert stock["market_cap_research"]["upside_text"]
            assert stock["segment_market_view"]["market_size_text"]
            assert stock["segment_market_view"]["company_share_text"]
            assert stock["stage_snapshot"]["name"]
            assert stock["market_cap_snapshot"]["current_anchor"]
            assert "chart_url" in stock
            assert stock["chart_frequency_label"] == "主页图形"
            assert "chart_unavailable_reason" in stock
            assert stock["main_matches"]
            assert stock["candidate_matches"]

            for match_group in [stock["main_matches"], stock["candidate_matches"]]:
                for match in match_group:
                    assert len(match["code"]) == 6
                    assert match["display_name"].startswith(match["code"])
                    assert 0 <= match["serenity_fit_score"] <= 20
                    assert match["serenity_fit_level"] in {"高", "中高", "中", "观察"}
                    assert match["analysis_detail_label"] == "查看个股分析"
                    assert match["analysis_detail_url"].startswith("/a_share_matches/stock-analysis/match/")
                    assert "financial_summary_short" in match
                    assert "analysis_source_label" in match
                    assert "source_validation" in match
                    assert match["selection_reason"]["summary"]
                    assert match["selection_reason"]["fit_basis"]
                    assert match["scarcity_view"]["label"]
                    assert match["scarcity_view"]["detail"]
                    assert match["capacity_view"]["label"]
                    assert match["capacity_view"]["detail"]
                    assert match["pricing_view"]["label"]
                    assert match["pricing_view"]["detail"]
                    assert match["market_cap_research"]["current_text"]
                    assert match["market_cap_research"]["upside_text"]
                    assert match["segment_market_view"]["market_size_text"]
                    assert match["segment_market_view"]["company_share_text"]
                    assert match["supply_chain_position"]
                    assert match["mapping_path"]
                    assert match["judgement"]
                    assert match["major_risk"]
                    assert match["chart_url"].startswith("/?market=a&code=")
                    assert "&embedded=1" in match["chart_url"]
                    assert "&lite_chart=1" in match["chart_url"]
                    assert match["chart_frequency_label"] == "主页图形"

        for related in theme["theme_related_stocks"]:
            assert len(related["code"]) == 6
            assert related["display_name"].startswith(related["code"])
            assert related["role"]
            assert related["serenity_angle"]
            assert related["stage"]
            assert related["market_cap_hint"]
            assert related["major_risk"]
            assert "source_validation" in related
            assert related["detail_url"].endswith(f"/{theme['slug']}/{related['code']}")
            assert related["chart_url"].startswith("/?market=a&code=")
            assert "&embedded=1" in related["chart_url"]
            assert "&lite_chart=1" in related["chart_url"]
            assert related["chart_frequency_label"] == "主页图形"

    robotics_theme = next(theme for theme in catalog["themes"] if theme["title"] == "机器人 / 具身智能 / 核心部件")
    quantum_theme = next(theme for theme in catalog["themes"] if theme["title"] == "量子计算 / 精密制造 / 上游设备")

    robotics_symbols = {stock["symbol"] for stock in robotics_theme["project_stocks"]}
    assert {"VPG", "AEVA", "SSYS"} <= robotics_symbols
    assert any("传感" in match["role"] or "感知" in match["role"] for stock in robotics_theme["project_stocks"] for match in stock["main_matches"] + stock["candidate_matches"])
    assert any("伺服" in match["role"] or "控制" in match["role"] or "减速器" in match["role"] for stock in robotics_theme["project_stocks"] for match in stock["main_matches"] + stock["candidate_matches"])
    assert any("结构" in match["role"] or "3D" in match["role"] or "制造" in match["role"] for stock in robotics_theme["project_stocks"] for match in stock["main_matches"] + stock["candidate_matches"])

    quantum_symbols = {stock["symbol"] for stock in quantum_theme["project_stocks"]}
    assert {"INFQ", "ALRIB"} <= quantum_symbols
    assert any("量子" in match["role"] or "系统" in match["role"] for stock in quantum_theme["project_stocks"] for match in stock["main_matches"] + stock["candidate_matches"])
    assert any("激光" in match["role"] or "光源" in match["role"] for stock in quantum_theme["project_stocks"] for match in stock["main_matches"] + stock["candidate_matches"])
    assert any("真空" in match["role"] or "设备" in match["role"] or "制造" in match["role"] for stock in quantum_theme["project_stocks"] for match in stock["main_matches"] + stock["candidate_matches"])

    optical_theme = next(theme for theme in catalog["themes"] if theme["title"] == "光模块 / CPO / 光子器件")
    optical_related_codes = {item["code"] for item in optical_theme["theme_related_stocks"]}
    assert {"300308", "300502", "300394", "688498", "688313", "002281"} <= optical_related_codes

    materials_theme = next(theme for theme in catalog["themes"] if theme["title"] == "光子材料 / 衬底 / 外延 / SOI")
    materials_related_codes = {item["code"] for item in materials_theme["theme_related_stocks"]}
    assert {"688126", "002428", "600703"} <= materials_related_codes

    interconnect_theme = next(theme for theme in catalog["themes"] if theme["title"] == "AI互连 / 连接芯片 / AEC")
    interconnect_symbols = {stock["symbol"] for stock in interconnect_theme["project_stocks"]}
    assert {"AVGO", "ALAB", "CRDO"} <= interconnect_symbols
    interconnect_related_codes = {item["code"] for item in interconnect_theme["theme_related_stocks"]}
    assert {"688008", "605277", "002130"} <= interconnect_related_codes

    authenticated_themes = [optical_theme, materials_theme, interconnect_theme]
    for theme in authenticated_themes:
        for stock in theme["project_stocks"]:
            assert stock["source_validation"]["status"] == "已认证"
            assert len(stock["source_validation"]["sources"]) >= 2
            for match in stock["main_matches"]:
                assert match["source_validation"]["status"] == "已认证"
                assert len(match["source_validation"]["sources"]) >= 2
        for related in theme["theme_related_stocks"]:
            assert related["source_validation"]["status"] == "已认证"
            assert len(related["source_validation"]["sources"]) >= 2


def test_a_share_matches_template_renders_new_serenity_fit_structure():
    html = _render_a_share_matches_template()

    assert "Serenity Fit 数值 + 等级" in html
    assert "主题加权指数" in html
    assert "主题导航" in html
    assert "主映射" in html
    assert "候选池" in html
    assert "Serenity 视角" in html
    assert "Serenity 推荐理由" in html
    assert "查看推荐脉络" in html
    assert 'class="theme-nav-link is-active"' in html
    assert 'href="#theme-光模块-CPO-光子器件"' in html
    assert 'data-theme-section' in html
    assert 'data-symbol="SIVE"' in html
    assert 'data-a-share-code="688498"' in html
    assert "18/20" in html
    assert "项目股票价格" in html
    assert "查看相关 Tweets" in html
    assert "当前阶段" in html
    assert "市值空间" in html
    assert "为什么符合" in html
    assert "稀缺性" in html
    assert "扩产难度" in html
    assert "涨价能力" in html
    assert "研究市值" in html
    assert "实时市值" in html
    assert "环节市场规模" in html
    assert "公司份额" in html
    assert "财务分析" in html
    assert "查看个股分析" in html
    assert "机器人 / 具身智能 / 核心部件" in html
    assert "量子计算 / 精密制造 / 上游设备" in html
    assert "VPG" in html
    assert "AEVA" in html
    assert "SSYS" in html
    assert "INFQ" in html
    assert "ALRIB" in html
    assert "AVGO" in html
    assert "--theme-accent:" in html
    assert "Serenity 主题扩展股票" in html
    assert "按主题扩展挖掘" in html
    assert "查看扩展详情" in html
    assert 'data-related-code="688498"' in html
    assert 'data-theme-index-card="true"' in html
    assert 'data-theme-index-codes=' in html
    assert 'data-theme-index-slug=' in html
    assert 'data-theme-index-lookback="max"' in html
    assert 'data-theme-index-reference-date' in html
    assert 'role="button"' in html
    assert 'tabindex="0"' in html
    assert 'theme-index-value' in html
    assert 'theme-index-stats' in html
    assert "当日涨跌幅" in html
    assert "当日振幅" in html
    assert "当年涨跌幅" in html
    assert "当年振幅" in html
    assert "基准日" in html
    assert "基点 1000" in html
    assert "theme-index-history-modal" in html
    assert "/a_share_matches/theme_index_history" in html
    assert "/a_share_matches/theme_index_snapshots" in html
    assert "loadThemeIndexHistory" in html
    assert "loadThemeIndexSnapshots" in html
    assert "renderThemeIndexHistoryChart" in html
    assert "20日" in html
    assert "60日" in html
    assert "250日" in html
    assert "最长" in html
    assert "自定义基准日" in html
    assert 'type="date"' in html
    assert 'id="theme-index-reference-date-input"' in html
    assert 'id="theme-index-reference-date-apply"' in html
    assert 'id="theme-index-reference-date-reset"' in html
    assert "lookback_label" in html
    assert "is_max_range" in html
    assert "theme-index-history-grid-line" in html
    assert "theme-index-history-latest-dot" in html
    assert "theme-index-history-mode" in html
    assert "theme-index-history-hover-card" in html
    assert "renderThemeIndexHistoryCandles" in html
    assert "syncThemeIndexHistoryHover" in html
    assert "theme-index-history-crosshair-x" in html
    assert "theme-index-history-crosshair-y" in html
    assert "calculateThemeIndexHistorySummary" in html
    assert 'id="theme-index-history-daily-change"' in html
    assert 'id="theme-index-history-daily-amplitude"' in html
    assert 'id="theme-index-history-ytd-change"' in html
    assert 'id="theme-index-history-ytd-amplitude"' in html
    assert "区间涨跌" in html
    assert "最大回撤" in html
    assert "指数定义" in html
    assert "开" in html
    assert "高" in html
    assert "低" in html
    assert "收" in html
    assert "查看缠论图" in html
    assert 'id="chart-modal"' in html
    assert 'id="chart-modal-loading"' in html
    assert 'data-chart-trigger' in html
    assert "requestIdleCallback" in html
    assert "preloadChartUrl" in html
    assert "查看推荐脉络" in html
    assert "查看扩展详情" in html
    assert "Serenity Mapping" not in html


def test_optical_chain_selection_metrics_include_deep_research_fields():
    catalog = get_a_share_match_catalog()

    optical_theme = next(theme for theme in catalog["themes"] if theme["title"] == "光模块 / CPO / 光子器件")
    optical_matches = {
        match["code"]: match
        for stock in optical_theme["project_stocks"]
        for match in stock["main_matches"] + stock["candidate_matches"]
    }

    source_photonics = optical_matches["688498"]
    assert "Lumentum" in source_photonics["selection_reason"]["fit_basis"]
    assert "200G EML" in source_photonics["selection_reason"]["summary"]
    assert "验证" in source_photonics["capacity_view"]["detail"]
    assert "260亿美元" in source_photonics["segment_market_view"]["market_size_text"]
    assert "中个位数" in source_photonics["segment_market_view"]["company_share_text"]

    tfc = optical_matches["300394"]
    assert "1.6T 光引擎量产" in tfc["selection_reason"]["summary"]
    assert "缺料" in tfc["scarcity_view"]["detail"]
    assert "FAU / ELS / 光引擎" in tfc["segment_market_view"]["market_size_text"]
    assert "结构升级" in tfc["pricing_view"]["detail"]

    accelink = optical_matches["002281"]
    assert "Omdia" in accelink["selection_reason"]["fit_basis"]
    assert "1.6T 已具备批量交付能力" in accelink["selection_reason"]["summary"]
    assert "5.9%" in accelink["segment_market_view"]["company_share_text"]

    innolight = optical_matches["300308"]
    assert "800G/1.6T" in innolight["selection_reason"]["summary"]
    assert "结构升级" in innolight["pricing_view"]["detail"]

    eoptolink = optical_matches["300502"]
    assert "1.6T 产品订单" in eoptolink["selection_reason"]["summary"]
    assert "锁定备货" in eoptolink["capacity_view"]["detail"]
    assert "硅光产品" in eoptolink["pricing_view"]["detail"]

    shijia = optical_matches["688313"]
    assert "1.6T 光模块用 AWG" in shijia["selection_reason"]["summary"]
    assert "MT-FA" in shijia["selection_reason"]["fit_basis"]
    assert "小批量" in shijia["capacity_view"]["detail"]

    jcg = optical_matches["688167"]
    assert "小批量供应" in jcg["selection_reason"]["summary"]
    assert "四大环节" in jcg["selection_reason"]["fit_basis"]
    assert "1.6T、3.2T" in jcg["segment_market_view"]["market_size_text"]

    materials_theme = next(theme for theme in catalog["themes"] if theme["title"] == "光子材料 / 衬底 / 外延 / SOI")
    materials_matches = {
        match["code"]: match
        for stock in materials_theme["project_stocks"]
        for match in stock["main_matches"] + stock["candidate_matches"]
    }

    yunnan_germanium = materials_matches["002428"]
    assert "批量供货" in yunnan_germanium["selection_reason"]["summary"]
    assert "价格有所上涨" in yunnan_germanium["pricing_view"]["detail"]
    assert "18个月" in yunnan_germanium["capacity_view"]["detail"]

    sanan = materials_matches["600703"]
    assert "100G EML" in sanan["selection_reason"]["summary"]
    assert "CW光源" in sanan["selection_reason"]["fit_basis"]
    assert "平台型" in sanan["scarcity_view"]["detail"]

    shanghai_silicon = materials_matches["688126"]
    assert "Soitec" in shanghai_silicon["selection_reason"]["fit_basis"]
    assert "FY26 超过 1 亿美元" in shanghai_silicon["selection_reason"]["summary"]
    assert "1 亿美元" in shanghai_silicon["segment_market_view"]["market_size_text"]

    leon = materials_matches["605358"]
    assert "12英寸硅片" in leon["selection_reason"]["summary"]
    assert "平均出货价格环比逐季提升" in leon["pricing_view"]["detail"]
    assert "12英寸硅外延片" in leon["segment_market_view"]["market_size_text"]

    god = materials_matches["688233"]
    assert "刻蚀" in god["selection_reason"]["summary"]
    assert "晶体生长到硅电极成品" in god["selection_reason"]["fit_basis"]
    assert "本土主流存储芯片制造厂" in god["scarcity_view"]["detail"]
    assert "12英寸曲面电极" in god["capacity_view"]["detail"]
    assert "第二增长曲线" in god["pricing_view"]["detail"]
    assert "70亿元" in god["segment_market_view"]["market_size_text"]
    assert "认证" in god["capacity_view"]["detail"]

    caster = materials_matches["002222"]
    assert "WSS" in caster["selection_reason"]["summary"]
    assert "光隔离器" in caster["selection_reason"]["fit_basis"]
    assert "高功率光隔离器" in caster["scarcity_view"]["detail"]
    assert "ROADM" in caster["segment_market_view"]["market_size_text"]

    hcsemi = materials_matches["300323"]
    assert "Micro LED光模块" in hcsemi["selection_reason"]["summary"]
    assert "首批光通信样品已交付海外客户" in hcsemi["selection_reason"]["fit_basis"]
    assert "全球首条6英寸Micro LED规模化量产线" in hcsemi["capacity_view"]["detail"]
    assert "验证期" in hcsemi["pricing_view"]["detail"]


def test_optical_theme_related_stocks_include_yofc_with_price_cycle_evidence():
    catalog = get_a_share_match_catalog()
    optical_theme = next(theme for theme in catalog["themes"] if theme["title"] == "光模块 / CPO / 光子器件")

    related = {item["code"]: item for item in optical_theme["theme_related_stocks"]}
    assert "601869" in related
    yofc = related["601869"]
    assert "空芯光纤" in yofc["serenity_angle"]
    assert "价格" in yofc["market_cap_hint"]
    assert yofc["source_validation"]["status"] == "已认证"


def test_remaining_themes_selection_metrics_include_serenity_deep_research_fields():
    catalog = get_a_share_match_catalog()

    storage_theme = next(theme for theme in catalog["themes"] if theme["title"] == "存储 / NAND / HBM")
    storage_matches = {
        match["code"]: match
        for stock in storage_theme["project_stocks"]
        for match in stock["main_matches"] + stock["candidate_matches"]
    }
    giga = storage_matches["603986"]
    assert "利基 DRAM" in giga["selection_reason"]["summary"]
    assert "SLC NAND" in giga["selection_reason"]["fit_basis"]
    assert "量价齐升" in giga["pricing_view"]["detail"]

    cloud_theme = next(theme for theme in catalog["themes"] if theme["title"] == "算力 / 云基础设施 / GPU云")
    cloud_matches = {
        match["code"]: match
        for stock in cloud_theme["project_stocks"]
        for match in stock["main_matches"] + stock["candidate_matches"]
    }
    sugon = cloud_matches["603019"]
    assert "供给侧算力平台" in sugon["selection_reason"]["summary"]
    assert "GPU 真正上电交付" in sugon["selection_reason"]["fit_basis"]
    assert "资源调度" in sugon["scarcity_view"]["detail"]

    idc = cloud_matches["300738"]
    assert "通电机房" in idc["scarcity_view"]["detail"]
    assert "上电节奏" in idc["capacity_view"]["detail"]

    foundry_theme = next(theme for theme in catalog["themes"] if theme["title"] == "晶圆代工 / 特色工艺")
    foundry_matches = {
        match["code"]: match
        for stock in foundry_theme["project_stocks"]
        for match in stock["main_matches"] + stock["candidate_matches"]
    }
    smic = foundry_matches["688981"]
    assert "95.8%" in smic["capacity_view"]["detail"]
    assert "先进逻辑" in smic["selection_reason"]["summary"]

    huahong = foundry_matches["688347"]
    assert "106.1%" in huahong["capacity_view"]["detail"]
    assert "功率器件" in huahong["selection_reason"]["fit_basis"]

    packaging_theme = next(theme for theme in catalog["themes"] if theme["title"] == "先进封装 / 玻璃基板 / HBM设备")
    packaging_matches = {
        match["code"]: match
        for stock in packaging_theme["project_stocks"]
        for match in stock["main_matches"] + stock["candidate_matches"]
    }
    hwatsing = packaging_matches["688120"]
    assert "CMP" in hwatsing["selection_reason"]["summary"]
    assert "平坦化" in hwatsing["selection_reason"]["fit_basis"]
    assert "CoWoS" in hwatsing["segment_market_view"]["market_size_text"]

    changchuan = packaging_matches["300604"]
    assert "先进测试" in changchuan["selection_reason"]["summary"]
    assert "良率" in changchuan["scarcity_view"]["detail"]

    power_theme = next(theme for theme in catalog["themes"] if theme["title"] == "电力 / 公用事业 / 电网设备")
    power_matches = {
        match["code"]: match
        for stock in power_theme["project_stocks"]
        for match in stock["main_matches"] + stock["candidate_matches"]
    }
    nari = power_matches["600406"]
    assert "354.32 亿元" in nari["capacity_view"]["detail"]
    assert "调度自动化" in nari["selection_reason"]["fit_basis"]

    space_theme = next(theme for theme in catalog["themes"] if theme["title"] == "商业航天 / 卫星 / 发射")
    space_matches = {
        match["code"]: match
        for stock in space_theme["project_stocks"]
        for match in stock["main_matches"] + stock["candidate_matches"]
    }
    cssc = space_matches["600118"]
    assert "24颗" in cssc["selection_reason"]["summary"]
    assert "系统级" in cssc["selection_reason"]["fit_basis"]

    hanxun = space_matches["300762"]
    assert "千帆星座" in hanxun["selection_reason"]["fit_basis"]
    assert "已签未完合同" in hanxun["capacity_view"]["detail"]

    minerals_theme = next(theme for theme in catalog["themes"] if theme["title"] == "关键矿物 / 稀土 / 战略材料")
    minerals_matches = {
        match["code"]: match
        for stock in minerals_theme["project_stocks"]
        for match in stock["main_matches"] + stock["candidate_matches"]
    }
    northern_rare_earth = minerals_matches["600111"]
    assert "170,001吨" in northern_rare_earth["selection_reason"]["summary"]
    assert "66.93%" in northern_rare_earth["selection_reason"]["fit_basis"]

    ai_metals_theme = next(theme for theme in catalog["themes"] if theme["title"] == "AI稀有金属 / 关键矿物 / 上游资源")
    ai_metals_symbols = {stock["symbol"] for stock in ai_metals_theme["project_stocks"]}
    assert {"AXTI", "MP"} <= ai_metals_symbols
    ai_metals_matches = {
        match["code"]: match
        for stock in ai_metals_theme["project_stocks"]
        for match in stock["main_matches"] + stock["candidate_matches"]
    }
    assert {"002428", "600111", "300748"} <= set(ai_metals_matches)
    yunnan_germanium = ai_metals_matches["002428"]
    assert "光纤级四氯化锗" in yunnan_germanium["selection_reason"]["summary"]
    assert "磷化铟" in yunnan_germanium["selection_reason"]["fit_basis"]
    jinli = ai_metals_matches["300748"]
    assert "高性能钕铁硼" in jinli["selection_reason"]["summary"]
    assert "人形机器人" in jinli["selection_reason"]["fit_basis"]

    robotics_theme = next(theme for theme in catalog["themes"] if theme["title"] == "机器人 / 具身智能 / 核心部件")
    robotics_matches = {
        match["code"]: match
        for stock in robotics_theme["project_stocks"]
        for match in stock["main_matches"] + stock["candidate_matches"]
    }
    leader = robotics_matches["301413"]
    assert "高精度传感器" in leader["selection_reason"]["summary"]
    assert "力控闭环" in leader["selection_reason"]["fit_basis"]

    step = robotics_matches["688160"]
    assert "3.71 亿元" in step["selection_reason"]["summary"]
    assert "旋转关节平台方案" in step["selection_reason"]["fit_basis"]

    quantum_theme = next(theme for theme in catalog["themes"] if theme["title"] == "量子计算 / 精密制造 / 上游设备")
    quantum_matches = {
        match["code"]: match
        for stock in quantum_theme["project_stocks"]
        for match in stock["main_matches"] + stock["candidate_matches"]
    }
    quantumctek = quantum_matches["688027"]
    assert "1.20 亿元" in quantumctek["selection_reason"]["summary"]
    assert "两台量子计算整机交付" in quantumctek["selection_reason"]["fit_basis"]

    amecc = quantum_matches["688012"]
    assert "前段制造设备" in amecc["selection_reason"]["summary"]
    assert "MBE" in amecc["selection_reason"]["fit_basis"]


def test_remaining_themes_have_authenticated_project_and_match_sources():
    catalog = get_a_share_match_catalog()

    representative_pairs = [
        ("存储 / NAND / HBM", "SNDK", "603986"),
        ("算力 / 云基础设施 / GPU云", "NBIS", "603019"),
        ("晶圆代工 / 特色工艺", "TSM", "688981"),
        ("先进封装 / 玻璃基板 / HBM设备", "TOWA", "688120"),
        ("商业航天 / 卫星 / 发射", "RKLB", "600118"),
        ("电力 / 公用事业 / 电网设备", "XLU", "600406"),
        ("关键矿物 / 稀土 / 战略材料", "VNP", "600111"),
        ("AI稀有金属 / 关键矿物 / 上游资源", "AXTI", "002428"),
        ("机器人 / 具身智能 / 核心部件", "VPG", "688160"),
        ("量子计算 / 精密制造 / 上游设备", "INFQ", "688027"),
    ]

    for theme_title, project_symbol, match_code in representative_pairs:
        theme = next(theme for theme in catalog["themes"] if theme["title"] == theme_title)
        project = next(stock for stock in theme["project_stocks"] if stock["symbol"] == project_symbol)
        match = next(
            item
            for stock in theme["project_stocks"]
            for item in stock["main_matches"] + stock["candidate_matches"]
            if item["code"] == match_code
        )

        assert project["source_validation"]["status"] == "已认证"
        assert len(project["source_validation"]["sources"]) >= 2
        assert match["source_validation"]["status"] == "已认证"
        assert len(match["source_validation"]["sources"]) >= 2
def test_all_project_stocks_have_rich_tweet_note_content():
    catalog = get_a_share_match_catalog()

    for theme in catalog["themes"]:
        for stock in theme["project_stocks"]:
            note = get_project_tweet_note(stock["symbol"])
            assert note["industry_chain"]["title"]
            assert note["industry_chain"]["nodes"]
            assert note["stage_view"]["name"]
            assert note["market_cap_view"]["current_anchor"]
            assert note["market_cap_view"]["scenarios"]


def test_theme_related_detail_template_renders_core_sections():
    catalog = get_a_share_match_catalog()
    theme = catalog["themes"][0]
    related = theme["theme_related_stocks"][0]

    html = _render_theme_related_detail_template(
        {
            "theme_title": theme["title"],
            "theme_accent": theme["accent"],
            "stock": related,
        }
    )

    assert "Serenity 主题扩展股票" in html
    assert theme["title"] in html
    assert related["display_name"] in html
    assert "Serenity 角度" in html
    assert "当前阶段" in html
    assert "市值空间判断" in html
    assert "主要风险" in html
    assert "查看缠论图" in html


def test_a_share_matches_template_renders_quote_auto_refresh_hooks():
    html = _render_a_share_matches_template()

    assert "loadProjectStockQuotes" in html
    assert "loadAShareMatchQuotes" in html
    assert "refreshPriceQuotesIfNeeded" in html
    assert "setInterval(refreshPriceQuotesIfNeeded" in html


def test_theme_related_detail_template_renders_quote_auto_refresh_hooks():
    html = _render_theme_related_detail_template(
        {
            "theme_title": "机器人 / 具身智能 / 核心部件",
            "theme_slug": "robotics",
            "theme_accent": "#7dd3fc",
            "theme_accent_soft": "rgba(125, 211, 252, 0.12)",
            "theme_accent_line": "rgba(125, 211, 252, 0.18)",
            "stock": {
                "code": "688160",
                "display_name": "688160 步科股份",
                "role": "控制器 / 驱控系统",
                "serenity_bucket": "核心卡位",
                "stage": "客户验证 -> 收入放量",
                "serenity_angle": "更接近机器人关节控制层。",
                "market_cap_hint": "更像高成长平台样本。",
                "major_risk": "客户验证节奏低于预期。",
                "chart_url": "/?market=a&code=688160",
            },
        }
    )

    assert "loadRelatedStockQuote" in html
    assert "refreshRelatedStockQuoteIfNeeded" in html
    assert "setInterval(refreshRelatedStockQuoteIfNeeded" in html
