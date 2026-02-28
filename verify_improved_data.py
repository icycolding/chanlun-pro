import os
import sys
import pandas as pd

# 将项目 src 目录添加到 sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chanlun.db import db

def verify_improved_financial_data():
    """
    验证改进后的财务数据，展示第二列全称信息的提取效果
    """
    print("=== 验证改进后的财务数据 ===")
    
    # 查询最新的财务数据
    results = db.company_financials_query(
        code='LI',
        report_date_start=pd.to_datetime('2024-01-01').date(),
        limit=20
    )
    
    if results:
        print(f"\n找到 {len(results)} 条记录")
        print("\n前20条记录展示（包含完整项目名称）:")
        print("-" * 100)
        print(f"{'序号':<4} {'报告日期':<12} {'项目名称':<50} {'数值':<15}")
        print("-" * 100)
        
        for i, record in enumerate(results[:20], 1):
            print(f"{i:<4} {record.report_date} {record.item_name:<50} {record.item_value:<15.2f}")
        
        print("\n=== 数据改进效果分析 ===")
        
        # 统计包含括号描述的项目数量
        items_with_description = [r for r in results if '(' in r.item_name and ')' in r.item_name]
        print(f"包含详细描述的项目数量: {len(items_with_description)} / {len(results)}")
        print(f"描述信息覆盖率: {len(items_with_description)/len(results)*100:.1f}%")
        
        # 展示一些典型的改进示例
        print("\n典型的项目名称改进示例:")
        for i, record in enumerate(items_with_description[:5], 1):
            print(f"{i}. {record.item_name}")
            
        # 统计不同报告期的数据
        dates = list(set([r.report_date for r in results]))
        dates.sort(reverse=True)
        print(f"\n可用的报告期数量: {len(dates)}")
        print("最近的报告期:")
        for date in dates[:5]:
            count = len([r for r in results if r.report_date == date])
            print(f"  {date}: {count} 个项目")
            
    else:
        print("未找到财务数据")

if __name__ == "__main__":
    verify_improved_financial_data()