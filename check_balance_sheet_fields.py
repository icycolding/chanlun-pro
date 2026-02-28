#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os

# 添加项目路径
sys.path.append('/Users/jiming/Documents/trae/chanlun-pro/src')

from chanlun.db import db, TableByCompanyFinancials

def check_balance_sheet_fields():
    """检查数据库中资产负债表和现金流量表的实际字段格式"""
    
    try:
        with db.Session() as session:
            # 查询理想汽车的财务数据，按报表类型分组
            results = session.query(
                TableByCompanyFinancials.statement_type,
                TableByCompanyFinancials.item_name,
                TableByCompanyFinancials.item_value,
                TableByCompanyFinancials.report_date
            ).filter(
                TableByCompanyFinancials.code == 'LI'
            ).order_by(
                TableByCompanyFinancials.report_date.desc(),
                TableByCompanyFinancials.statement_type,
                TableByCompanyFinancials.item_name
            ).limit(200).all()
        
            if not results:
                print("❌ 未找到理想汽车的财务数据")
                return
            
            # 按报表类型分组显示
            statement_types = {}
            for statement_type, item_name, item_value, report_date in results:
                if statement_type not in statement_types:
                    statement_types[statement_type] = []
                statement_types[statement_type].append((item_name, item_value, report_date))
        
        print("\n📊 理想汽车财务数据字段格式分析:")
        print("=" * 60)
        
        for statement_type, items in statement_types.items():
            print(f"\n📋 **{statement_type}** (共{len(items)}个字段)")
            print("-" * 40)
            
            # 显示前10个字段作为示例
            for i, (item_name, item_value, report_date) in enumerate(items[:10]):
                print(f"  {i+1:2d}. {item_name} = {item_value} ({report_date})")
            
            if len(items) > 10:
                print(f"     ... 还有{len(items)-10}个字段")
        
        # 特别关注资产负债表和现金流量表的关键字段
        print("\n🔍 **关键字段搜索结果:**")
        print("=" * 60)
        
        # 搜索资产负债表关键字段
        balance_sheet_keywords = ['资产', 'Asset', 'ATAS', 'ATOT', 'ACAE', 'ACUR', 'Total Assets', 'Current Assets']
        liability_keywords = ['负债', 'Liab', 'LTLL', 'LTOT', 'LCLO', 'LCUR', 'Total Liabilities', 'Current Liabilities']
        equity_keywords = ['权益', 'Equity', 'QTLE', 'QTCO', 'Total Equity']
        cashflow_keywords = ['现金流', 'Cash Flow', 'OTLO', 'ITLI', 'FTLF', 'Operating Cash Flow']
        
        all_keywords = balance_sheet_keywords + liability_keywords + equity_keywords + cashflow_keywords
        
        # 显示所有报表类型的统计
        print("\n📈 **报表类型统计:**")
        print("-" * 40)
        for statement_type, items in statement_types.items():
            print(f"  • {statement_type}: {len(items)}个字段")
            # 显示该报表类型的前5个字段示例
            print(f"    示例字段: {', '.join([item[0][:30] + '...' if len(item[0]) > 30 else item[0] for item in items[:3]])}")
        
        found_fields = []
        for statement_type, item_name, item_value, report_date in results:
            for keyword in all_keywords:
                if keyword.upper() in item_name.upper():
                    found_fields.append((statement_type, item_name, item_value, report_date))
                    break
        
        if found_fields:
            for statement_type, item_name, item_value, report_date in found_fields[:20]:
                print(f"  • [{statement_type}] {item_name} = {item_value} ({report_date})")
        else:
            print("  ❌ 未找到匹配的关键字段")
        
    except Exception as e:
        print(f"❌ 查询数据库时出错: {str(e)}")

if __name__ == "__main__":
    check_balance_sheet_fields()