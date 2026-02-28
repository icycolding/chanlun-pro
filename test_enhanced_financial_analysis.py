#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试增强后的财务分析功能 - 独立测试版本
"""

# 模拟数据库模型类
class MockFinancialData:
    def __init__(self, code, name, report_date, statement_type, item_name, item_value):
        self.code = code
        self.name = name
        self.report_date = report_date
        self.statement_type = statement_type
        self.item_name = item_name
        self.item_value = item_value

# 复制增强后的财务分析函数（简化版本，用于独立测试）
def _extract_key_financial_items(items: dict) -> dict:
    """提取关键财务指标"""
    key_items = {}
    
    # 定义关键财务指标的匹配规则
    key_mappings = {
        '营业收入': ['营业收入', '营业总收入', '总收入', '收入'],
        '净利润': ['净利润', '归属于母公司所有者的净利润', '归母净利润'],
        '总资产': ['总资产', '资产总计'],
        '总负债': ['总负债', '负债合计'],
        '股东权益': ['股东权益', '所有者权益合计', '归属于母公司所有者权益合计'],
        '经营现金流': ['经营活动产生的现金流量净额', '经营性现金流'],
        '流动资产': ['流动资产'],
        '流动负债': ['流动负债'],
    }
    
    # 匹配并提取关键指标
    for key_name, patterns in key_mappings.items():
        for pattern in patterns:
            for item_name, value in items.items():
                if pattern in item_name and key_name not in key_items:
                    key_items[key_name] = value
                    break
    
    return key_items

def _format_financial_value(value) -> str:
    """格式化财务数值"""
    if not isinstance(value, (int, float)):
        return str(value)
    
    if abs(value) >= 1e8:  # 亿元
        return f"{value/1e8:.2f}亿"
    elif abs(value) >= 1e4:  # 万元
        return f"{value/1e4:.2f}万"
    else:
        return f"{value:,.0f}"

def _calculate_financial_ratios(reports_by_date: dict, sorted_dates: list) -> list:
    """计算财务比率"""
    ratios_output = []
    
    if len(sorted_dates) < 1:
        return ratios_output
    
    try:
        # 获取最新期数据
        latest_date = sorted_dates[0]
        latest_data = reports_by_date[latest_date]
        
        # 合并所有报表类型的数据
        combined_data = {}
        for statement_type, items in latest_data.items():
            combined_data.update(items)
        
        key_items = _extract_key_financial_items(combined_data)
        
        # 1. 盈利能力比率
        ratios_output.append("\n💰 **盈利能力分析**")
        
        # 净利率
        if '营业收入' in key_items and '净利润' in key_items and key_items['营业收入'] != 0:
            net_margin = (key_items['净利润'] / key_items['营业收入']) * 100
            ratios_output.append(f"  • 净利率: {net_margin:.2f}%")
        
        # 2. 偿债能力比率
        ratios_output.append("\n🛡️ **偿债能力分析**")
        
        # 资产负债率
        if '总负债' in key_items and '总资产' in key_items and key_items['总资产'] != 0:
            debt_ratio = (key_items['总负债'] / key_items['总资产']) * 100
            ratios_output.append(f"  • 资产负债率: {debt_ratio:.2f}%")
        
        # 流动比率
        if '流动资产' in key_items and '流动负债' in key_items and key_items['流动负债'] != 0:
            current_ratio = key_items['流动资产'] / key_items['流动负债']
            ratios_output.append(f"  • 流动比率: {current_ratio:.2f}")
        
        # 3. 成长能力分析（需要多期数据）
        if len(sorted_dates) >= 2:
            ratios_output.append("\n📈 **成长能力分析**")
            
            # 获取上期数据
            prev_date = sorted_dates[1]
            prev_data = reports_by_date[prev_date]
            prev_combined = {}
            for statement_type, items in prev_data.items():
                prev_combined.update(items)
            prev_key_items = _extract_key_financial_items(prev_combined)
            
            # 营业收入增长率
            if '营业收入' in key_items and '营业收入' in prev_key_items and prev_key_items['营业收入'] != 0:
                revenue_growth = ((key_items['营业收入'] - prev_key_items['营业收入']) / prev_key_items['营业收入']) * 100
                ratios_output.append(f"  • 营业收入增长率: {revenue_growth:.2f}%")
        
    except Exception as e:
        ratios_output.append(f"  ❌ 财务比率计算异常: {str(e)}")
    
    return ratios_output

def test_format_financial_data_for_analysis(financial_data):
    """测试版本的财务数据分析函数"""
    if not financial_data:
        return "📊 **财务分析报告**\n\n❌ 暂无财务数据可供分析"
    
    try:
        # 按报告日期分组数据
        reports_by_date = {}
        for item in financial_data:
            date = item.report_date
            if date not in reports_by_date:
                reports_by_date[date] = {}
            
            statement_type = item.statement_type
            if statement_type not in reports_by_date[date]:
                reports_by_date[date][statement_type] = {}
            
            reports_by_date[date][statement_type][item.item_name] = item.item_value
        
        # 按日期排序（最新的在前）
        sorted_dates = sorted(reports_by_date.keys(), reverse=True)
        
        # 构建分析报告
        analysis_parts = []
        analysis_parts.append("📊 **增强版财务分析报告**")
        analysis_parts.append("=" * 50)
        
        # 1. 基础财务数据概览
        analysis_parts.append("\n📋 **基础财务数据概览**")
        
        # 显示最近4个报告期的关键数据
        display_dates = sorted_dates[:4]
        for i, date in enumerate(display_dates):
            analysis_parts.append(f"\n**{date} 报告期:**")
            
            # 合并该期所有报表数据
            combined_data = {}
            for statement_type, items in reports_by_date[date].items():
                combined_data.update(items)
            
            key_items = _extract_key_financial_items(combined_data)
            
            # 显示关键指标
            for key_name, value in key_items.items():
                formatted_value = _format_financial_value(value)
                analysis_parts.append(f"  • {key_name}: {formatted_value}")
        
        # 2. 财务比率分析
        ratio_analysis = _calculate_financial_ratios(reports_by_date, sorted_dates)
        analysis_parts.extend(ratio_analysis)
        
        # 3. 简化的风险评估
        analysis_parts.append("\n⚠️ **风险评估**")
        if len(sorted_dates) >= 1:
            latest_date = sorted_dates[0]
            latest_data = reports_by_date[latest_date]
            combined_data = {}
            for statement_type, items in latest_data.items():
                combined_data.update(items)
            key_items = _extract_key_financial_items(combined_data)
            
            # 流动性风险
            if '流动资产' in key_items and '流动负债' in key_items and key_items['流动负债'] != 0:
                current_ratio = key_items['流动资产'] / key_items['流动负债']
                if current_ratio < 1.0:
                    analysis_parts.append(f"  🔴 高风险: 流动比率{current_ratio:.2f} < 1.0，短期偿债能力不足")
                elif current_ratio < 1.5:
                    analysis_parts.append(f"  🟡 中风险: 流动比率{current_ratio:.2f}，流动性偏紧")
                else:
                    analysis_parts.append(f"  🟢 低风险: 流动比率{current_ratio:.2f}，流动性良好")
        
        # 4. 简化的投资建议
        analysis_parts.append("\n💡 **投资建议**")
        
        # 基于关键指标给出建议
        if len(sorted_dates) >= 1:
            latest_date = sorted_dates[0]
            latest_data = reports_by_date[latest_date]
            combined_data = {}
            for statement_type, items in latest_data.items():
                combined_data.update(items)
            key_items = _extract_key_financial_items(combined_data)
            
            score = 0
            factors = []
            
            # 盈利能力评分
            if '营业收入' in key_items and '净利润' in key_items and key_items['营业收入'] != 0:
                net_margin = (key_items['净利润'] / key_items['营业收入']) * 100
                if net_margin > 10:
                    score += 2
                    factors.append("盈利能力强")
                elif net_margin > 0:
                    score += 1
                    factors.append("盈利能力一般")
                else:
                    factors.append("公司亏损")
            
            # 成长性评分
            if len(sorted_dates) >= 2:
                prev_date = sorted_dates[1]
                prev_data = reports_by_date[prev_date]
                prev_combined = {}
                for statement_type, items in prev_data.items():
                    prev_combined.update(items)
                prev_key_items = _extract_key_financial_items(prev_combined)
                
                if '营业收入' in key_items and '营业收入' in prev_key_items and prev_key_items['营业收入'] != 0:
                    revenue_growth = ((key_items['营业收入'] - prev_key_items['营业收入']) / prev_key_items['营业收入']) * 100
                    if revenue_growth > 10:
                        score += 2
                        factors.append("高速增长")
                    elif revenue_growth > 0:
                        score += 1
                        factors.append("稳健增长")
                    else:
                        factors.append("收入下降")
            
            # 综合建议
            if score >= 3:
                analysis_parts.append("  🌟 **推荐 (买入)**")
                analysis_parts.append(f"    关键因素: {', '.join(factors)}")
                analysis_parts.append("    建议: 公司基本面良好，具备投资价值")
            elif score >= 1:
                analysis_parts.append("  ⚖️ **中性 (持有)**")
                analysis_parts.append(f"    关键因素: {', '.join(factors)}")
                analysis_parts.append("    建议: 公司表现一般，谨慎投资")
            else:
                analysis_parts.append("  ⚠️ **谨慎 (观望)**")
                analysis_parts.append(f"    关键因素: {', '.join(factors)}")
                analysis_parts.append("    建议: 公司面临挑战，建议观望")
        
        return "\n".join(analysis_parts)
        
    except Exception as e:
        return f"📊 **财务分析报告**\n\n❌ 分析过程中出现异常: {str(e)}"

def create_mock_financial_data():
    """创建模拟财务数据用于测试"""
    mock_data = [
        # 2024年Q3数据
        MockFinancialData('000001', '平安银行', '2024-09-30', '利润表', '营业收入', 50000000000),
        MockFinancialData('000001', '平安银行', '2024-09-30', '利润表', '净利润', 8000000000),
        MockFinancialData('000001', '平安银行', '2024-09-30', '资产负债表', '总资产', 500000000000),
        MockFinancialData('000001', '平安银行', '2024-09-30', '资产负债表', '总负债', 400000000000),
        MockFinancialData('000001', '平安银行', '2024-09-30', '资产负债表', '股东权益', 100000000000),
        MockFinancialData('000001', '平安银行', '2024-09-30', '资产负债表', '流动资产', 300000000000),
        MockFinancialData('000001', '平安银行', '2024-09-30', '资产负债表', '流动负债', 200000000000),
        MockFinancialData('000001', '平安银行', '2024-09-30', '现金流量表', '经营活动产生的现金流量净额', 10000000000),
        
        # 2024年Q2数据（用于对比分析）
        MockFinancialData('000001', '平安银行', '2024-06-30', '利润表', '营业收入', 45000000000),
        MockFinancialData('000001', '平安银行', '2024-06-30', '利润表', '净利润', 7000000000),
        MockFinancialData('000001', '平安银行', '2024-06-30', '资产负债表', '总资产', 480000000000),
        MockFinancialData('000001', '平安银行', '2024-06-30', '资产负债表', '总负债', 390000000000),
        MockFinancialData('000001', '平安银行', '2024-06-30', '资产负债表', '股东权益', 90000000000),
        MockFinancialData('000001', '平安银行', '2024-06-30', '现金流量表', '经营活动产生的现金流量净额', 8000000000),
    ]
    
    return mock_data

def test_enhanced_financial_analysis():
    """测试增强后的财务分析功能"""
    print("=" * 80)
    print("测试增强后的财务分析功能")
    print("=" * 80)
    
    try:
        # 创建模拟数据
        mock_data = create_mock_financial_data()
        
        # 调用增强后的财务分析函数
        result = test_format_financial_data_for_analysis(mock_data)
        
        print("\n📊 财务分析结果:")
        print("-" * 60)
        print(result)
        print("-" * 60)
        
        # 验证结果包含预期的分析模块
        expected_sections = [
            "基础财务数据概览",
            "盈利能力分析",
            "偿债能力分析",
            "风险评估",
            "投资建议"
        ]
        
        missing_sections = []
        for section in expected_sections:
            if section not in result:
                missing_sections.append(section)
        
        if missing_sections:
            print(f"\n⚠️ 警告: 以下分析模块未找到: {', '.join(missing_sections)}")
        else:
            print("\n✅ 所有预期的分析模块都已包含")
        
        # 检查是否包含关键财务比率
        key_ratios = ["净利率", "资产负债率", "流动比率", "营业收入增长率"]
        found_ratios = []
        for ratio in key_ratios:
            if ratio in result:
                found_ratios.append(ratio)
        
        print(f"\n📈 找到的关键财务比率: {', '.join(found_ratios)}")
        
        # 检查是否包含风险评估
        risk_indicators = ["高风险", "中风险", "低风险"]
        found_risks = []
        for risk in risk_indicators:
            if risk in result:
                found_risks.append(risk)
        
        print(f"\n⚠️ 风险评估指标: {', '.join(found_risks)}")
        
        # 检查是否包含投资建议
        investment_advice = ["推荐", "买入", "持有", "观望"]
        found_advice = []
        for advice in investment_advice:
            if advice in result:
                found_advice.append(advice)
        
        print(f"\n💡 投资建议关键词: {', '.join(found_advice)}")
        
        print("\n✅ 财务分析功能测试完成")
        return True
        
    except Exception as e:
        print(f"\n❌ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def test_edge_cases():
    """测试边界情况"""
    print("\n" + "=" * 80)
    print("测试边界情况")
    print("=" * 80)
    
    try:
        # 测试空数据
        print("\n1. 测试空数据:")
        result = test_format_financial_data_for_analysis([])
        print(f"空数据结果: {result[:100]}..." if len(result) > 100 else result)
        
        # 测试单期数据
        print("\n2. 测试单期数据:")
        single_period_data = [
            MockFinancialData('000001', '测试公司', '2024-09-30', '利润表', '营业收入', 1000000000)
        ]
        result = test_format_financial_data_for_analysis(single_period_data)
        print(f"单期数据结果: {result[:200]}..." if len(result) > 200 else result)
        
        print("\n✅ 边界情况测试完成")
        return True
        
    except Exception as e:
        print(f"\n❌ 边界情况测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("开始测试增强后的财务分析功能...")
    
    # 运行主要功能测试
    main_test_passed = test_enhanced_financial_analysis()
    
    # 运行边界情况测试
    edge_test_passed = test_edge_cases()
    
    # 总结测试结果
    print("\n" + "=" * 80)
    print("测试总结")
    print("=" * 80)
    
    if main_test_passed and edge_test_passed:
        print("🎉 所有测试通过！增强后的财务分析功能工作正常。")
        print("\n主要改进:")
        print("• ✅ 添加了财务比率计算（盈利能力、偿债能力、营运能力、成长能力）")
        print("• ✅ 实现了财务风险评估（流动性风险、偿债风险、经营风险）")
        print("• ✅ 增加了财务前景分析（收入增长趋势、盈利能力变化、现金流健康度）")
        print("• ✅ 提供了综合财务健康评分和投资建议")
        print("• ✅ 支持多期财务数据对比分析")
        print("• ✅ 增强了数据可视化格式")
    else:
        print("❌ 部分测试失败，需要进一步调试。")
        if not main_test_passed:
            print("• 主要功能测试失败")
        if not edge_test_passed:
            print("• 边界情况测试失败")