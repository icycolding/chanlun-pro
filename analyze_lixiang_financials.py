#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
理想汽车财务数据分析脚本
功能：
1. 数据概览和基本统计
2. 关键财务指标计算
3. 历史趋势分析
4. 生成完整的财务分析报告
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

import pandas as pd
from datetime import datetime
from chanlun.db import DB
import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib import rcParams

# 设置中文字体
rcParams['font.sans-serif'] = ['SimHei', 'Arial Unicode MS', 'DejaVu Sans']
rcParams['axes.unicode_minus'] = False

class LiXiangFinancialAnalyzer:
    def __init__(self):
        self.db = DB()
        self.company_code = 'KH.02015'
        self.company_name = '理想汽车'
        self.data = None
        
    def load_data(self):
        """加载理想汽车财务数据"""
        print(f"正在加载{self.company_name}财务数据...")
        
        # 使用DB类的company_financials_query方法
        results = self.db.company_financials_query(code=self.company_code, limit=10000)
        
        if not results:
            print(f"未找到{self.company_name}的财务数据")
            return False
        
        # 将结果转换为DataFrame
        data_list = []
        for record in results:
            data_list.append({
                'code': record.code,
                'name': record.name,
                'report_date': record.report_date,
                'statement_type': record.statement_type,
                'item_name': record.item_name,
                'item_value': record.item_value
            })
            
        self.data = pd.DataFrame(data_list)
        self.data['report_date'] = pd.to_datetime(self.data['report_date'])
        
        print(f"成功加载{len(self.data)}条财务数据记录")
        return True
    
    def data_overview(self):
        """数据概览"""
        print("\n" + "="*60)
        print(f"          {self.company_name}财务数据概览")
        print("="*60)
        
        print(f"公司代码: {self.company_code}")
        print(f"公司名称: {self.company_name}")
        print(f"数据记录总数: {len(self.data)}条")
        
        # 报表类型统计
        statement_counts = self.data['statement_type'].value_counts()
        print(f"\n报表类型分布:")
        for stmt_type, count in statement_counts.items():
            print(f"  {stmt_type}: {count}条记录")
        
        # 时间范围
        date_range = self.data['report_date'].agg(['min', 'max'])
        print(f"\n数据时间范围: {date_range['min'].strftime('%Y-%m-%d')} 至 {date_range['max'].strftime('%Y-%m-%d')}")
        
        # 报告期统计
        period_counts = self.data['report_date'].value_counts().sort_index(ascending=False)
        print(f"\n各报告期数据量:")
        for period, count in period_counts.head(10).items():
            print(f"  {period.strftime('%Y-%m-%d')}: {count}条记录")
    
    def extract_key_metrics(self):
        """提取关键财务指标"""
        print("\n" + "="*60)
        print("          关键财务指标分析")
        print("="*60)
        
        # 由于ECOR字段有重复（Vehicle sales和Other sales and services），需要特殊处理
        # 先分离出车辆销售和其他销售服务数据
        vehicle_sales_data = self.data[self.data['item_name'].str.contains('Vehicle sales', na=False)].copy()
        other_sales_data = self.data[self.data['item_name'].str.contains('Other sales and services', na=False)].copy()
        
        # 重命名以区分
        vehicle_sales_data['item_name'] = 'ECOR_Vehicle_Sales'
        other_sales_data['item_name'] = 'ECOR_Other_Sales'
        
        # 合并数据
        processed_data = pd.concat([
            self.data[~self.data['item_name'].str.contains('ECOR', na=False)],
            vehicle_sales_data,
            other_sales_data
        ])
        
        # 创建透视表
        pivot_data = processed_data.pivot_table(
            index='report_date', 
            columns='item_name', 
            values='item_value', 
            aggfunc='first'
        ).fillna(0)
        
        # 定义关键指标映射（基于实际数据字段）
        key_metrics_mapping = {
            '车辆销售收入': ['ECOR_Vehicle_Sales'],  # Vehicle sales
            '其他销售服务收入': ['ECOR_Other_Sales', 'RNTS (Other sales and services)'],  # Other sales and services
            '总营业收入': ['RTLR (Total Revenue)'],  # Total Revenue
            '税前净利润': ['EIBT (Net Income Before Taxes)', 'VPTI (Normalized Income Before Taxes)'],  # Net Income Before Taxes
            '净利润': ['NINC (Net Income)', 'GDNI (Diluted Net Income)', 'NIBX (Net Income Before Extra. Items)'],  # Net Income
            '归属于普通股股东净利润': ['CIAC (Income Available to Com Excl ExtraOrd)', 'VIAC (Normalized Inc. Avail to Com.)', 'XNIC (Income Available to Com Incl ExtraOrd)'],  # Income Available to Com
            '归属于非控股股东净利润': ['CMIN (Net income/ (loss) attributable to nonco)', 'VMIN (Net income/ (loss) attributable to nonco)'],  # Net income attributable to nonco
            '员工薪酬费用': ['ERAD (Employee compensation)', 'VRAD (Employee compensation)'],  # Employee compensation
            '销售管理费用中员工薪酬': ['ELAR (Employee compensation in SGA)'],  # Employee compensation in SGA
            '利息收入': ['NIIN (Interest Income - Non Bank)'],  # Interest Income
            '利息费用': ['VIEX (Interest expense)', 'NIEN (Interest expense)'],  # Interest expense
            '股权激励费用': ['VSCP (Stock Option Compen Expense - Pre-Tax)'],  # Stock Option Compensation
            '所得税费用': ['TTAX (Provision for Income Taxes)', 'VITN (Inc Tax Ex Impact of Sp Items)'],  # Income Tax
        }
        
        print("\n主要财务指标趋势 (单位: 万元):")
        print("-" * 80)
        
        # 获取最近几个报告期
        recent_periods = sorted(pivot_data.index, reverse=True)[:8]
        
        for period in recent_periods:
            print(f"\n报告期: {period.strftime('%Y-%m-%d')}")
            period_data = pivot_data.loc[period]
            
            for metric_name, possible_codes in key_metrics_mapping.items():
                value = 0
                found_code = None
                for code in possible_codes:
                    if code in period_data and period_data[code] != 0:
                        value = period_data[code]
                        found_code = code
                        break
                
                if found_code:
                    print(f"  {metric_name}: {value:,.0f} ({found_code})")
                else:
                    print(f"  {metric_name}: 数据不可用")
    
    def calculate_financial_ratios(self):
        """计算财务比率"""
        print("\n" + "="*60)
        print("          财务比率分析")
        print("="*60)
        
        pivot_data = self.data.pivot_table(
            index='report_date', 
            columns='item_name', 
            values='item_value', 
            aggfunc='first'
        ).fillna(0)
        
        print("\n主要财务比率计算:")
        print("-" * 50)
        
        recent_periods = sorted(pivot_data.index, reverse=True)[:4]
        
        for period in recent_periods:
            print(f"\n{period.strftime('%Y-%m-%d')} 财务比率:")
            period_data = pivot_data.loc[period]
            
            # 获取营业收入（车辆销售收入 + 其他销售服务收入）
            vehicle_sales = period_data.get('ECOR_Vehicle_Sales', 0)
            other_sales = period_data.get('ECOR_Other_Sales', 0)
            total_revenue = period_data.get('RTLR (Total Revenue)', 0) or (vehicle_sales + other_sales)
            
            # 净利润
            net_profit = period_data.get('NINC (Net Income)', 0) or period_data.get('GDNI (Diluted Net Income)', 0) or period_data.get('NIBX (Net Income Before Extra. Items)', 0)
            
            # 税前净利润
            profit_before_tax = period_data.get('EIBT (Net Income Before Taxes)', 0) or period_data.get('VPTI (Normalized Income Before Taxes)', 0)
            
            if total_revenue > 0:
                print(f"  总营业收入: {total_revenue:,.0f}万元")
                print(f"    - 车辆销售收入: {vehicle_sales:,.0f}万元")
                print(f"    - 其他销售服务收入: {other_sales:,.0f}万元")
                
                # 净利率计算
                if net_profit != 0:
                    net_margin = (net_profit / total_revenue) * 100
                    print(f"  净利率: {net_margin:.2f}%")
                else:
                    print(f"  净利率: 无法计算")
                
                # 税前利润率
                if profit_before_tax != 0:
                    pretax_margin = (profit_before_tax / total_revenue) * 100
                    print(f"  税前利润率: {pretax_margin:.2f}%")
                else:
                    print(f"  税前利润率: 无法计算")
            else:
                print(f"  营业收入数据不可用")
            
            # 员工薪酬费用率
            employee_cost = period_data.get('ERAD (Employee compensation)', 0) or period_data.get('VRAD (Employee compensation)', 0)
            if total_revenue > 0 and employee_cost > 0:
                employee_ratio = (employee_cost / total_revenue) * 100
                print(f"  员工薪酬费用率: {employee_ratio:.2f}%")
            
            # 股权激励费用率
            stock_compensation = period_data.get('VSCP (Stock Option Compen Expense - Pre-Tax)', 0)
            if total_revenue > 0 and stock_compensation > 0:
                stock_comp_ratio = (stock_compensation / total_revenue) * 100
                print(f"  股权激励费用率: {stock_comp_ratio:.2f}%")
            
            print(f"  净利润: {net_profit:,.0f}万元")
            print(f"  税前净利润: {profit_before_tax:,.0f}万元")
    
    def trend_analysis(self):
        """趋势分析"""
        print("\n" + "="*60)
        print("          历史趋势分析")
        print("="*60)
        
        pivot_data = self.data.pivot_table(
            index='report_date', 
            columns='item_name', 
            values='item_value', 
            aggfunc='first'
        ).fillna(0)
        
        # 按时间排序
        pivot_data = pivot_data.sort_index()
        
        print("\n营业收入增长趋势:")
        print("-" * 40)
        
        # 计算总营业收入（车辆销售 + 其他销售服务）
        vehicle_sales_data = pivot_data.get('ECOR_Vehicle_Sales', pd.Series(dtype=float))
        other_sales_data = pivot_data.get('ECOR_Other_Sales', pd.Series(dtype=float))
        total_revenue_data = pivot_data.get('RTLR (Total Revenue)', pd.Series(dtype=float))
        
        # 如果没有RTLR，则用车辆销售 + 其他销售服务计算
        if total_revenue_data.sum() == 0 and (vehicle_sales_data.sum() > 0 or other_sales_data.sum() > 0):
            total_revenue_data = vehicle_sales_data.fillna(0) + other_sales_data.fillna(0)
        
        if total_revenue_data.sum() > 0:
            revenue_data = total_revenue_data[total_revenue_data > 0]  # 过滤掉0值
            
            revenue_values = list(revenue_data.values)
            for i, (date, revenue) in enumerate(revenue_data.items()):
                if i > 0:
                    prev_revenue = revenue_values[i-1]
                    growth_rate = ((revenue - prev_revenue) / prev_revenue) * 100
                    print(f"{date.strftime('%Y-%m-%d')}: {revenue:,.0f}万元 (环比增长: {growth_rate:+.1f}%)")
                else:
                    print(f"{date.strftime('%Y-%m-%d')}: {revenue:,.0f}万元")
        else:
            print("营业收入数据不可用")
        
        print("\n净利润趋势:")
        print("-" * 40)
        
        # 查找净利润数据
        profit_data = None
        for col in ['NINC (Net Income)', 'GDNI (Diluted Net Income)', 'NIBX (Net Income Before Extra. Items)']:
            if col in pivot_data.columns and pivot_data[col].sum() != 0:
                profit_data = pivot_data[col]
                break
        
        if profit_data is not None:
            profit_data = profit_data[profit_data != 0]  # 过滤掉0值
            
            for date, profit in profit_data.items():
                status = "盈利" if profit > 0 else "亏损"
                print(f"{date.strftime('%Y-%m-%d')}: {profit:,.0f}万元 ({status})")
        else:
            print("净利润数据不可用")
        
        print("\n税前净利润趋势:")
        print("-" * 40)
        
        # 查找税前净利润数据
        pretax_profit_data = None
        for col in ['EIBT (Net Income Before Taxes)', 'VPTI (Normalized Income Before Taxes)']:
            if col in pivot_data.columns and pivot_data[col].sum() != 0:
                pretax_profit_data = pivot_data[col]
                break
        
        if pretax_profit_data is not None:
            pretax_profit_data = pretax_profit_data[pretax_profit_data != 0]  # 过滤掉0值
            
            for date, profit in pretax_profit_data.items():
                status = "盈利" if profit > 0 else "亏损"
                print(f"{date.strftime('%Y-%m-%d')}: {profit:,.0f}万元 ({status})")
        else:
            print("税前净利润数据不可用")
    
    def generate_report(self):
        """生成完整的财务分析报告"""
        print("\n" + "="*60)
        print("          理想汽车财务分析报告")
        print("="*60)
        print(f"报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        if not self.data.empty:
            latest_date = self.data['report_date'].max()
            print(f"数据截止日期: {latest_date.strftime('%Y-%m-%d')}")
        
        print("\n一、数据来源说明:")
        print("- 数据来源: 公司财务数据库")
        print("- 报表类型: 主要为损益表数据")
        print("- 数据完整性: 基于现有损益表数据进行分析")
        print("- 注意事项: 缺少资产负债表和现金流量表数据，部分财务比率无法计算")
        
        print("\n二、主要发现:")
        
        # 基于数据的主要发现
        pivot_data = self.data.pivot_table(
            index='report_date', 
            columns='item_name', 
            values='item_value', 
            aggfunc='first'
        ).fillna(0)
        
        if not pivot_data.empty:
            latest_period = pivot_data.index.max()
            latest_data = pivot_data.loc[latest_period]
            
            revenue = latest_data.get('RNTS', 0) or latest_data.get('RTLR', 0)
            profit = latest_data.get('EIBT', 0) or latest_data.get('EIAT', 0)
            
            print(f"- 最新报告期({latest_period.strftime('%Y-%m-%d')})营业收入: {revenue:,.0f}万元")
            
            if profit > 0:
                print(f"- 最新报告期净利润: {profit:,.0f}万元 (盈利状态)")
            elif profit < 0:
                print(f"- 最新报告期净利润: {profit:,.0f}万元 (亏损状态)")
            else:
                print(f"- 净利润数据不可用")
            
            # 计算毛利率
            cost = latest_data.get('CIAC', 0) or latest_data.get('CMIN', 0)
            if revenue > 0:
                gross_margin = ((revenue - cost) / revenue) * 100
                print(f"- 最新毛利率: {gross_margin:.2f}%")
        
        print("\n三、投资建议:")
        print("- 建议关注公司营业收入增长趋势")
        print("- 重点关注盈利能力改善情况")
        print("- 建议补充资产负债表和现金流量表数据以进行更全面的分析")
        print("- 持续跟踪研发投入和市场表现")
        
        print("\n" + "="*60)
        print("                报告结束")
        print("="*60)
    
    def run_analysis(self):
        """运行完整的财务分析"""
        if not self.load_data():
            return
        
        self.data_overview()
        self.extract_key_metrics()
        self.calculate_financial_ratios()
        self.trend_analysis()
        self.generate_report()

def main():
    """主函数"""
    print("理想汽车财务数据分析系统")
    print("=" * 50)
    
    analyzer = LiXiangFinancialAnalyzer()
    analyzer.run_analysis()

if __name__ == "__main__":
    main()