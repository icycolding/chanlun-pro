import pandas as pd
import datetime
import os
import sys

# 将项目 src 目录添加到 sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chanlun.db import db

def debug_process_financial_statements(xls_path: str, company_code: str, company_name: str):
    """
    调试版本的财务报表处理函数，包含详细的调试信息。
    """
    print(f"Starting to process file: {xls_path}")
    
    try:
        xls = pd.ExcelFile(xls_path)
        print(f"Excel file loaded successfully. Sheet names: {xls.sheet_names}")
    except FileNotFoundError:
        print(f"Error: Excel file not found at {xls_path}")
        return
    except Exception as e:
        print(f"Error loading Excel file: {e}")
        return

    for sheet_name in xls.sheet_names:
        print(f"\nProcessing sheet: {sheet_name}")
        
        if any(keyword in sheet_name for keyword in ['资产负债表', '利润表', '现金流量表', '损益表']):
            print(f"Sheet {sheet_name} is a financial statement, processing...")
            
            try:
                df = pd.read_excel(xls, sheet_name=sheet_name, index_col=0)
                print(f"DataFrame shape: {df.shape}")
                print(f"DataFrame columns: {list(df.columns)}")
                print(f"DataFrame index (first 5): {list(df.index[:5])}")
                
                df = df.replace('--', pd.NA).dropna(how='all')
                print(f"After cleaning, DataFrame shape: {df.shape}")
                
                for report_date_str in df.columns:
                    print(f"\nProcessing date column: {report_date_str}")
                    
                    try:
                        report_date = pd.to_datetime(report_date_str).date()
                        print(f"Parsed date: {report_date}")
                    except ValueError as e:
                        print(f"Skipping invalid date column: {report_date_str} in sheet: {sheet_name}, error: {e}")
                        continue

                    financials = []
                    for item_name, row in df[[report_date_str]].iterrows():
                        item_value = row[report_date_str]
                        if pd.notna(item_value) and item_name and isinstance(item_name, str):
                            try:
                                float_value = float(item_value)
                                financials.append({
                                    'item_name': item_name.strip(),
                                    'item_value': float_value
                                })
                            except (ValueError, TypeError) as e:
                                print(f"Skipping item {item_name} with value {item_value}: {e}")
                    
                    print(f"Prepared {len(financials)} financial items for insertion")
                    if len(financials) > 0:
                        print(f"Sample items: {financials[:3]}")

                    if financials:
                        print(f"Inserting data for {company_name} ({company_code}), Report Date: {report_date}, Statement: {sheet_name}, Items: {len(financials)}")
                        
                        try:
                            success = db.company_financials_insert(
                                code=company_code,
                                name=company_name,
                                statement_type=sheet_name,
                                report_date=report_date,
                                financials=financials
                            )
                            if success:
                                print(f"Successfully inserted data for {report_date} in {sheet_name}")
                            else:
                                print(f"Failed to insert data for {report_date} in {sheet_name}")
                        except Exception as e:
                            print(f"Exception during insertion: {e}")
                    else:
                        print(f"No valid financial data found for {report_date} in {sheet_name}")
                        
            except Exception as e:
                print(f"Error processing sheet {sheet_name}: {e}")
        else:
            print(f"Sheet {sheet_name} is not a financial statement, skipping...")

if __name__ == "__main__":
    print("Starting debug financial data processing...")
    
    # 设置 Django 环境 (如果您的项目是 Django 项目)
    try:
        import django
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'your_project.settings')
        django.setup()
        print("Django setup completed")
    except ImportError:
        print("Not a Django project, skipping Django setup")
    except Exception as e:
        print(f"Django setup error: {e}")
        
    xls_file_path = '/Users/jiming/Documents/trae/chanlun-pro/company/理想汽车.xls'
    debug_process_financial_statements(xls_file_path, 'LI', '理想汽车')
    print("\nDebug financial data processing finished.")