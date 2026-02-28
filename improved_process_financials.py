import pandas as pd
import datetime
import os
import sys

# 将项目 src 目录添加到 sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chanlun.db import db

def process_financial_statements_improved(xls_path: str, company_code: str, company_name: str):
    """
    改进的财务报表处理函数，正确处理Excel文件结构，包括第二列的全称信息。
    """
    try:
        xls = pd.ExcelFile(xls_path)
    except FileNotFoundError:
        print(f"Error: Excel file not found at {xls_path}")
        return

    for sheet_name in xls.sheet_names:
        print(f"Processing sheet: {sheet_name}")
        
        if any(keyword in sheet_name for keyword in ['资产负债表', '利润表', '现金流量表', '损益表']):
            # 读取原始数据，不设置index_col
            df_raw = pd.read_excel(xls, sheet_name=sheet_name)
            print(f"Raw DataFrame shape: {df_raw.shape}")
            print(f"First few rows:")
            print(df_raw.head(10))
            
            # 找到日期行（通常在第4行，索引为3）
            date_row_idx = None
            for i in range(min(10, len(df_raw))):
                row = df_raw.iloc[i]
                # 检查是否包含年份信息
                if any(str(cell).strip().endswith('年3月') or str(cell).strip().endswith('年6月') or 
                      str(cell).strip().endswith('年9月') or str(cell).strip().endswith('年12月') 
                      for cell in row if pd.notna(cell)):
                    date_row_idx = i
                    print(f"Found date row at index: {date_row_idx}")
                    break
            
            if date_row_idx is None:
                print(f"Could not find date row in sheet: {sheet_name}")
                continue
                
            # 提取日期列
            date_row = df_raw.iloc[date_row_idx]
            date_columns = []
            for col_idx, cell in enumerate(date_row):
                if pd.notna(cell) and isinstance(cell, str):
                    cell_str = str(cell).strip()
                    if ('年' in cell_str and ('月' in cell_str)):
                        date_columns.append((col_idx, cell_str))
            
            print(f"Found date columns: {date_columns}")
            
            # 从日期行之后开始处理数据
            data_start_row = date_row_idx + 1
            
            for col_idx, date_str in date_columns:
                try:
                    # 解析日期字符串，例如 "2024年12月" -> "2024-12-31"
                    if '年' in date_str and '月' in date_str:
                        year_month = date_str.replace('年', '-').replace('月', '')
                        # 假设是季度末日期
                        if year_month.endswith('-3'):
                            report_date = pd.to_datetime(year_month + '-31').date()
                        elif year_month.endswith('-6'):
                            report_date = pd.to_datetime(year_month + '-30').date()
                        elif year_month.endswith('-9'):
                            report_date = pd.to_datetime(year_month + '-30').date()
                        elif year_month.endswith('-12'):
                            report_date = pd.to_datetime(year_month + '-31').date()
                        else:
                            # 默认使用月末
                            report_date = pd.to_datetime(year_month + '-01').date()
                            report_date = report_date.replace(day=28)  # 安全的月末日期
                    else:
                        continue
                        
                except (ValueError, AttributeError) as e:
                    print(f"Skipping invalid date: {date_str}, error: {e}")
                    continue

                financials = []
                # 从数据开始行处理每一行
                for row_idx in range(data_start_row, len(df_raw)):
                    row = df_raw.iloc[row_idx]
                    
                    # 第一列是项目名称
                    item_name = row.iloc[0] if len(row) > 0 else None
                    # 第二列是项目全称/描述
                    item_description = row.iloc[1] if len(row) > 1 else None
                    # 对应日期列的数值
                    item_value = row.iloc[col_idx] if len(row) > col_idx else None
                    
                    # 检查数据有效性
                    if (pd.notna(item_name) and pd.notna(item_value) and 
                        isinstance(item_name, str) and item_name.strip() and
                        str(item_value).replace('.', '').replace('-', '').replace(',', '').isdigit()):
                        
                        try:
                            # 使用第二列作为完整的项目名称（如果存在且有效）
                            full_item_name = item_name.strip()
                            if pd.notna(item_description) and isinstance(item_description, str) and item_description.strip():
                                full_item_name = f"{item_name.strip()} ({item_description.strip()})"
                            
                            financials.append({
                                'item_name': full_item_name,
                                'item_value': float(str(item_value).replace(',', ''))
                            })
                        except (ValueError, TypeError) as e:
                            print(f"Error processing row {row_idx}: {e}")
                            continue

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
                else:
                    print(f"No valid financial data found for {date_str} in {sheet_name}")

if __name__ == "__main__":
    # 设置 Django 环境 (如果您的项目是 Django 项目)
    try:
        import django
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'your_project.settings')
        django.setup()
    except ImportError:
        # 如果不是 Django 项目，则忽略
        pass
        
    xls_file_path = '/Users/jiming/Documents/trae/chanlun-pro/company/理想汽车.xls'
    process_financial_statements_improved(xls_file_path, 'LI', '理想汽车')
    print("Improved financial data processing finished.")