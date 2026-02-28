import pandas as pd
import datetime
import os
import sys

# 将项目 src 目录添加到 sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chanlun.db import db
from chanlun.db import TableByCompanyFinancials

def clean_existing_data(company_code: str):
    """
    清理指定公司的现有财务数据
    """
    print(f"Cleaning existing data for company: {company_code}")
    with db.Session() as session:
        deleted_count = session.query(TableByCompanyFinancials).filter(
            TableByCompanyFinancials.code == company_code
        ).delete()
        session.commit()
        print(f"Deleted {deleted_count} existing records")

def process_financial_statements(xls_path: str, company_code: str, company_name: str):
    """
    处理财务报表Excel文件，并将其存入数据库。
    修正版本，适配实际的Excel文件格式。
    """
    try:
        xls = pd.ExcelFile(xls_path)
        print(f"Excel file loaded. Sheet names: {xls.sheet_names}")
    except FileNotFoundError:
        print(f"Error: Excel file not found at {xls_path}")
        return

    for sheet_name in xls.sheet_names:
        print(f"\nProcessing sheet: {sheet_name}")
        
        if any(keyword in sheet_name for keyword in ['资产负债表', '利润表', '现金流量表', '损益表']):
            print(f"Sheet {sheet_name} is a financial statement, processing...")
            
            # 先读取前几行来找到日期行
            df_header = pd.read_excel(xls, sheet_name=sheet_name, nrows=10)
            print(f"Looking for date row in first 10 rows...")
            
            # 查找包含日期的行
            date_row_idx = None
            for idx, row in df_header.iterrows():
                row_str = ' '.join([str(val) for val in row.values if pd.notna(val)])
                if '年' in row_str and '月' in row_str:
                    date_row_idx = idx
                    print(f"Found date row at index {idx}: {row_str[:100]}...")
                    break
            
            if date_row_idx is None:
                print(f"No date row found in sheet {sheet_name}, skipping...")
                continue
                
            # 使用找到的日期行作为header，并设置第一列为索引
            try:
                df = pd.read_excel(xls, sheet_name=sheet_name, header=date_row_idx, index_col=0)
                print(f"DataFrame loaded with header at row {date_row_idx}")
                print(f"DataFrame shape: {df.shape}")
                print(f"DataFrame columns: {list(df.columns)[:5]}...")  # 只显示前5列
                
                # 清理数据
                df = df.replace('--', pd.NA).replace('不可用', pd.NA).dropna(how='all')
                print(f"After cleaning, DataFrame shape: {df.shape}")
                
                # 处理每个日期列
                for col_name in df.columns:
                    if pd.isna(col_name):
                        continue
                        
                    col_str = str(col_name).strip()
                    print(f"\nProcessing column: {col_str}")
                    
                    # 尝试解析日期
                    try:
                        if '年' in col_str and '月' in col_str:
                            # 处理中文日期格式，如 "2024年12月"
                            import re
                            date_match = re.search(r'(\d{4})年(\d{1,2})月', col_str)
                            if date_match:
                                year = int(date_match.group(1))
                                month = int(date_match.group(2))
                                # 假设是季度末日期
                                if month in [3, 6, 9, 12]:
                                    if month == 3:
                                        day = 31
                                    elif month == 6:
                                        day = 30
                                    elif month == 9:
                                        day = 30
                                    else:  # month == 12
                                        day = 31
                                    report_date = datetime.date(year, month, day)
                                    print(f"Parsed date: {report_date}")
                                else:
                                    print(f"Skipping non-quarter month: {month}")
                                    continue
                            else:
                                print(f"Could not parse Chinese date format: {col_str}")
                                continue
                        else:
                            # 尝试标准日期解析
                            report_date = pd.to_datetime(col_str).date()
                            print(f"Parsed standard date: {report_date}")
                    except (ValueError, AttributeError) as e:
                        print(f"Skipping invalid date column: {col_str}, error: {e}")
                        continue

                    # 提取财务数据
                    financials = []
                    for item_name, item_value in df[col_name].items():
                        if pd.notna(item_value) and item_name and isinstance(item_name, str):
                            try:
                                # 尝试转换为数值
                                if isinstance(item_value, str):
                                    # 移除可能的逗号和其他格式字符
                                    clean_value = item_value.replace(',', '').replace('，', '')
                                    float_value = float(clean_value)
                                else:
                                    float_value = float(item_value)
                                    
                                financials.append({
                                    'item_name': item_name.strip(),
                                    'item_value': float_value
                                })
                            except (ValueError, TypeError):
                                # 跳过无法转换为数值的项目
                                continue

                    print(f"Prepared {len(financials)} financial items")
                    if len(financials) > 0:
                        print(f"Sample items: {financials[:3]}")

                    if financials:
                        print(f"Inserting data for {company_name} ({company_code}), Report Date: {report_date}, Statement: {sheet_name}, Items: {len(financials)}")
                        
                        # 逐个插入，避免批量插入时的唯一约束问题
                        success_count = 0
                        for financial in financials:
                            single_financial = [financial]
                            success = db.company_financials_insert(
                                code=company_code,
                                name=company_name,
                                statement_type=sheet_name,
                                report_date=report_date,
                                financials=single_financial
                            )
                            if success:
                                success_count += 1
                        
                        print(f"Successfully inserted {success_count}/{len(financials)} items for {report_date}")
                    else:
                        print(f"No valid financial data found for {col_str}")
                        
            except Exception as e:
                print(f"Error processing sheet {sheet_name}: {e}")
                import traceback
                traceback.print_exc()
        else:
            print(f"Sheet {sheet_name} is not a financial statement, skipping...")

if __name__ == "__main__":
    # 设置 Django 环境 (如果您的项目是 Django 项目)
    try:
        import django
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'your_project.settings')
        django.setup()
    except ImportError:
        pass
    
    company_code = 'LI'
    company_name = '理想汽车'
    xls_file_path = '/Users/jiming/Documents/trae/chanlun-pro/company/理想汽车.xls'
    
    # 先清理现有数据
    clean_existing_data(company_code)
    
    # 重新处理和插入数据
    process_financial_statements(xls_file_path, company_code, company_name)
    print("\nClean and insert financial data processing finished.")