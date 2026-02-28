import pandas as pd
import datetime
import os
import sys

# 将项目 src 目录添加到 sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chanlun.db import db

def process_financial_statements(xls_path: str, company_code: str, company_name: str):
    """
    处理财务报表Excel文件，并将其存入数据库。
    """
    try:
        xls = pd.ExcelFile(xls_path)
    except FileNotFoundError:
        print(f"Error: Excel file not found at {xls_path}")
        return

    for sheet_name in xls.sheet_names:
        if any(keyword in sheet_name for keyword in ['资产负债表', '利润表', '现金流量表', '损益表']):
            df = pd.read_excel(xls, sheet_name=sheet_name, index_col=0)
            df = df.replace('--', pd.NA).dropna(how='all')

            for report_date_str in df.columns:
                try:
                    report_date = pd.to_datetime(report_date_str).date()
                except ValueError:
                    print(f"Skipping invalid date column: {report_date_str} in sheet: {sheet_name}")
                    continue

                financials = []
                for item_name, row in df[[report_date_str]].iterrows():
                    item_value = row[report_date_str]
                    if pd.notna(item_value) and item_name and isinstance(item_name, str):
                        financials.append({
                            'item_name': item_name.strip(),
                            'item_value': float(item_value)
                        })

                if financials:
                    print(f"Inserting data for {company_name} ({company_code}), Report Date: {report_date}, Statement: {sheet_name}, Items: {len(financials)}")
                    success = db.company_financials_insert(
                        code=company_code,
                        name=company_name,
                        statement_type=sheet_name,
                        report_date=report_date,
                        financials=financials
                    )
                    if not success:
                        print(f"Failed to insert data for {report_date} in {sheet_name}")

if __name__ == "__main__":
    # 设置 Django 环境 (如果您的项目是 Django 项目)
    # 这部分可能需要根据您的项目结构进行调整
    try:
        import django
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'your_project.settings') # 替换 'your_project.settings'
        django.setup()
    except ImportError:
        # 如果不是 Django 项目，则忽略
        pass
        
    xls_file_path = '/Users/jiming/Documents/trae/chanlun-pro/company/理想汽车.xls'
    process_financial_statements(xls_file_path, 'LI', '理想汽车')
    print("Financial data processing finished.")