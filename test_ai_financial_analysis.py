#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试修改后的_format_financial_data_for_analysis函数
验证大模型分析功能
"""

import sys
import os
from datetime import datetime

# 模拟财务数据对象
class MockFinancialData:
    def __init__(self, report_date, statement_type, item_name, item_value):
        self.report_date = report_date
        self.statement_type = statement_type
        self.item_name = item_name
        self.item_value = item_value

# 模拟AIAnalyse类
class MockAIAnalyse:
    def __init__(self, market):
        self.market = market
    
    def req_openrouter_ai_model(self, prompt):
        # 模拟AI响应
        return {
            'ok': True,
            'msg': f"""
# 理想汽车财务数据深度分析报告

## 1. 财务表现概览

基于提供的2022-2024年财务数据，理想汽车展现出强劲的增长态势和显著的盈利能力改善：

- **营业收入快速增长**：从2022年的873亿元增长至2024年的1417亿元，年复合增长率达到27.4%
- **盈利能力显著提升**：从2022年亏损20亿元转为2024年盈利118亿元，实现了历史性的盈利转折
- **业务规模持续扩大**：三年间营业收入增长62.3%，显示出强劲的市场竞争力

## 2. 盈利能力分析

### 收入增长趋势
- 2023年营业收入1237亿元，同比增长41.7%
- 2024年营业收入1417亿元，同比增长14.5%
- 虽然增速有所放缓，但仍保持双位数增长

### 盈利质量评估
- **毛利率改善**：2022年毛利率约9.6%，2024年提升至16.6%
- **净利率转正**：从2022年的-2.3%提升至2024年的8.3%
- **盈利稳定性**：连续两年实现盈利，盈利能力持续改善

## 3. 成长性分析

### 收入增长率
- 2023年收入增长率：41.7%（高速增长）
- 2024年收入增长率：14.5%（稳健增长）
- 三年复合增长率：27.4%（优秀表现）

### 利润增长率
- 2023年净利润95亿元，实现扭亏为盈
- 2024年净利润118亿元，同比增长24.2%
- 利润增长速度超过收入增长，显示运营效率提升

## 4. 费用结构分析

### 研发投入
- 2022年研发费用105亿元，占收入12.0%
- 2023年研发费用132亿元，占收入10.7%
- 2024年研发费用156亿元，占收入11.0%
- 研发投入绝对金额持续增长，相对比例保持合理水平

### 销售费用
- 2022年销售费用62亿元，占收入7.1%
- 2023年销售费用78亿元，占收入6.3%
- 2024年销售费用89亿元，占收入6.3%
- 销售费用率控制良好，显示营销效率提升

## 5. 财务风险评估

### 盈利稳定性
- **风险较低**：已连续两年盈利，盈利趋势稳定
- **抗风险能力增强**：毛利率持续改善，为应对市场波动提供缓冲

### 成本控制能力
- **营业成本率下降**：从2022年的90.4%降至2024年的83.4%
- **费用控制良好**：研发和销售费用率保持在合理水平

## 6. 行业对比与竞争力

### 行业地位
- 在新能源汽车行业中，理想汽车的财务表现优于多数竞争对手
- 盈利能力的快速改善显示其商业模式的有效性
- 持续的研发投入保证了技术竞争力

### 市场竞争力
- 收入规模快速增长，市场份额持续提升
- 盈利能力领先于行业平均水平
- 品牌影响力和产品竞争力不断增强

## 7. 投资价值评估

### 投资亮点
1. **盈利能力强劲**：已实现稳定盈利，净利率持续改善
2. **成长性优秀**：收入和利润保持高速增长
3. **研发投入充足**：为长期发展奠定技术基础
4. **费用控制良好**：运营效率持续提升

### 投资建议
**推荐评级：买入**

理想汽车展现出优秀的财务表现和强劲的成长潜力，建议投资者关注：
- 短期内，公司盈利能力稳定，财务风险可控
- 中长期看，持续的研发投入和市场扩张将支撑业绩增长
- 在新能源汽车行业快速发展的背景下，公司有望继续受益

### 风险提示
1. 新能源汽车行业竞争激烈，需关注市场份额变化
2. 原材料价格波动可能影响毛利率
3. 宏观经济环境变化可能影响消费需求
4. 技术迭代风险需要持续关注

**总结**：理想汽车财务数据显示公司正处于快速发展期，盈利能力显著改善，成长性优秀，具有较高的投资价值。建议投资者在合理估值水平下积极配置。
"""
        }

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

def _call_ai_and_get_content(ai_client, prompt: str) -> str:
    """调用AI并获取内容的辅助函数"""
    try:
        result = ai_client.req_openrouter_ai_model(prompt)
        if result.get('ok', False):
            return result.get('msg', '').strip()
        else:
            error_msg = result.get('msg', '未知错误')
            return f"AI分析失败: {error_msg}"
    except Exception as e:
        return f"AI分析异常: {str(e)}"

def _format_financial_data_for_analysis(financial_data) -> str:
    """使用大模型对理想汽车财务数据进行深度分析"""
    if not financial_data:
        return "暂无财务数据"
    
    try:
        # 按报告日期和报表类型分组财务数据
        reports_by_date = {}
        for item in financial_data:
            report_date = item.report_date.strftime('%Y-%m-%d') if item.report_date else '未知日期'
            statement_type = item.statement_type or '未知类型'
            
            if report_date not in reports_by_date:
                reports_by_date[report_date] = {}
            
            if statement_type not in reports_by_date[report_date]:
                reports_by_date[report_date][statement_type] = {}
            
            item_name = item.item_name or '未知项目'
            item_value = item.item_value if item.item_value is not None else 0
            reports_by_date[report_date][statement_type][item_name] = item_value
        
        # 按日期排序（最新的在前）
        sorted_dates = sorted(reports_by_date.keys(), reverse=True)
        
        if not sorted_dates:
            return "暂无有效财务数据"
        
        # 构建完整的财务数据供大模型分析
        financial_data_text = "\n=== 理想汽车完整财务报表数据 ===\n\n"
        
        # 添加数据概览
        financial_data_text += f"数据范围: {sorted_dates[-1]} 至 {sorted_dates[0]}\n"
        financial_data_text += f"报告期数: {len(sorted_dates)}个\n"
        financial_data_text += f"数据记录总数: {len(financial_data)}条\n\n"
        
        # 详细展示每个报告期的财务数据
        for i, report_date in enumerate(sorted_dates):
            date_data = reports_by_date[report_date]
            financial_data_text += f"\n📅 **{report_date} 财务数据**\n"
            
            for statement_type, items in date_data.items():
                financial_data_text += f"\n📋 {statement_type}:\n"
                
                # 显示所有财务项目
                for item_name, value in items.items():
                    formatted_value = _format_financial_value(value)
                    financial_data_text += f"  • {item_name}: {formatted_value}\n"
        
        # 构建大模型分析提示词
        ai_prompt = f"""
你是一位资深的财务分析专家，请基于以下理想汽车的完整财务报表数据进行深度分析。

{financial_data_text}

请从以下维度进行全面深度分析：

1. **财务表现概览**
   - 分析理想汽车的整体财务状况和发展趋势
   - 识别关键财务指标的变化模式

2. **盈利能力分析**
   - 分析营业收入、净利润的增长趋势
   - 评估盈利质量和可持续性
   - 分析毛利率、净利率等关键比率

3. **成长性分析**
   - 评估收入增长率、利润增长率
   - 分析业务扩张能力和市场竞争力
   - 预测未来增长潜力

4. **费用结构分析**
   - 分析研发费用、员工薪酬等关键费用项目
   - 评估费用控制能力和运营效率
   - 分析费用与收入的匹配关系

5. **财务风险评估**
   - 基于现有数据评估财务风险
   - 分析盈利稳定性和波动性
   - 识别潜在的财务风险点

6. **行业对比与竞争力**
   - 结合新能源汽车行业特点分析理想汽车的竞争地位
   - 评估其在行业中的财务表现

7. **投资价值评估**
   - 基于财务数据评估理想汽车的投资价值
   - 提供投资建议和风险提示

请提供详细、专业、有洞察力的分析报告，字数控制在2000字左右。
"""
        
        # 调用大模型进行分析
        ai_client = MockAIAnalyse("a")  # 使用模拟的AI客户端
        analysis_result = _call_ai_and_get_content(ai_client, ai_prompt)
        
        return analysis_result
        
    except Exception as e:
        return f"财务数据分析异常: {str(e)}"

def create_mock_financial_data():
    """
    创建模拟的理想汽车财务数据
    """
    mock_data = []
    
    # 2024年数据
    date_2024 = datetime(2024, 12, 31)
    mock_data.extend([
        MockFinancialData(date_2024, "损益表", "CIAC 营业收入", 141700000000),  # 1417亿
        MockFinancialData(date_2024, "损益表", "CMIN 营业成本", 118200000000),  # 1182亿
        MockFinancialData(date_2024, "损益表", "ECOR 净利润", 11800000000),   # 118亿
        MockFinancialData(date_2024, "损益表", "CIRD 研发费用", 15600000000),  # 156亿
        MockFinancialData(date_2024, "损益表", "CISA 销售费用", 8900000000),   # 89亿
    ])
    
    # 2023年数据
    date_2023 = datetime(2023, 12, 31)
    mock_data.extend([
        MockFinancialData(date_2023, "损益表", "CIAC 营业收入", 123700000000),  # 1237亿
        MockFinancialData(date_2023, "损益表", "CMIN 营业成本", 105800000000),  # 1058亿
        MockFinancialData(date_2023, "损益表", "ECOR 净利润", 9500000000),    # 95亿
        MockFinancialData(date_2023, "损益表", "CIRD 研发费用", 13200000000),  # 132亿
        MockFinancialData(date_2023, "损益表", "CISA 销售费用", 7800000000),   # 78亿
    ])
    
    # 2022年数据
    date_2022 = datetime(2022, 12, 31)
    mock_data.extend([
        MockFinancialData(date_2022, "损益表", "CIAC 营业收入", 87300000000),   # 873亿
        MockFinancialData(date_2022, "损益表", "CMIN 营业成本", 78900000000),   # 789亿
        MockFinancialData(date_2022, "损益表", "ECOR 净利润", -2000000000),    # -20亿
        MockFinancialData(date_2022, "损益表", "CIRD 研发费用", 10500000000),  # 105亿
        MockFinancialData(date_2022, "损益表", "CISA 销售费用", 6200000000),   # 62亿
    ])
    
    return mock_data

def test_ai_financial_analysis():
    """
    测试使用大模型进行理想汽车财务数据分析
    """
    print("=== 测试大模型财务分析功能 ===")
    
    try:
        # 创建模拟财务数据
        print("正在创建模拟理想汽车财务数据...")
        financial_data = create_mock_financial_data()
        
        print(f"创建了 {len(financial_data)} 条财务数据")
        
        # 显示数据概览
        print("\n=== 数据概览 ===")
        dates = set()
        statement_types = set()
        for item in financial_data:
            if item.report_date:
                dates.add(item.report_date.strftime('%Y-%m-%d'))
            if item.statement_type:
                statement_types.add(item.statement_type)
        
        print(f"报告期数: {len(dates)}")
        print(f"报表类型: {list(statement_types)}")
        print(f"报告期: {sorted(dates)}")
        
        # 调用大模型分析函数
        print("\n=== 开始大模型分析 ===")
        print("正在调用大模型进行财务分析，请稍候...")
        
        analysis_result = _format_financial_data_for_analysis(financial_data)
        
        print("\n=== 大模型分析结果 ===")
        print(analysis_result)
        
        # 保存分析结果到文件
        with open('li_auto_ai_analysis_result.txt', 'w', encoding='utf-8') as f:
            f.write("理想汽车财务数据大模型分析报告\n")
            f.write("=" * 50 + "\n\n")
            f.write(analysis_result)
        
        print("\n✅ 分析完成！结果已保存到 li_auto_ai_analysis_result.txt")
        
    except Exception as e:
        print(f"❌ 测试过程中出现错误: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_ai_financial_analysis()