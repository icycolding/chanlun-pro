import os
import sys
import pandas as pd

# 将项目 src 目录添加到 sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chanlun.db import db

def test_query_financials():
    """
    测试查询公司财务数据并以 DataFrame 格式打印。
    """
    print("Querying financial data for LI...")
    
    # 查询理想汽车 (LI) 的财务数据
    financial_data = db.company_financials_query(
        code='LI',
        limit=200  # 限制返回的项目数量
    )
    
    if not financial_data:
        print("No financial data found for the specified criteria.")
        return

    # 将查询结果转换为 DataFrame 以便更好地显示
    data_list = []
    for record in financial_data:
        data_list.append({
            'Report Date': record.report_date,
            'Item Name': record.item_name,
            'Item Value': record.item_value
        })
    
    df = pd.DataFrame(data_list)
    
    # 按报告日期和项目名称排序
    df = df.sort_values(by=['Report Date', 'Item Name'], ascending=[False, True])
    
    print("--- 理想汽车 (LI) - 财务数据 ---")
    print(df.to_string())

if __name__ == "__main__":
    test_query_financials()