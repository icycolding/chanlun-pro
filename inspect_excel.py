import pandas as pd
import os

def inspect_excel_structure(xls_path: str):
    """
    检查Excel文件的原始结构
    """
    print(f"Inspecting Excel file: {xls_path}")
    
    try:
        xls = pd.ExcelFile(xls_path)
        print(f"Sheet names: {xls.sheet_names}")
        
        for sheet_name in xls.sheet_names:
            print(f"\n=== Sheet: {sheet_name} ===")
            
            # 读取前几行，不设置index_col
            df_raw = pd.read_excel(xls, sheet_name=sheet_name, nrows=10)
            print(f"Raw DataFrame shape: {df_raw.shape}")
            print(f"Raw DataFrame columns: {list(df_raw.columns)}")
            print("First 5 rows:")
            print(df_raw.head())
            
            print("\n--- Trying with header=1 ---")
            # 尝试使用第二行作为列名
            try:
                df_header1 = pd.read_excel(xls, sheet_name=sheet_name, header=1, nrows=10)
                print(f"Header=1 DataFrame shape: {df_header1.shape}")
                print(f"Header=1 DataFrame columns: {list(df_header1.columns)}")
                print("First 5 rows with header=1:")
                print(df_header1.head())
            except Exception as e:
                print(f"Error with header=1: {e}")
                
            print("\n--- Trying with header=2 ---")
            # 尝试使用第三行作为列名
            try:
                df_header2 = pd.read_excel(xls, sheet_name=sheet_name, header=2, nrows=10)
                print(f"Header=2 DataFrame shape: {df_header2.shape}")
                print(f"Header=2 DataFrame columns: {list(df_header2.columns)}")
                print("First 5 rows with header=2:")
                print(df_header2.head())
            except Exception as e:
                print(f"Error with header=2: {e}")
                
    except Exception as e:
        print(f"Error reading Excel file: {e}")

if __name__ == "__main__":
    xls_file_path = '/Users/jiming/Documents/trae/chanlun-pro/company/理想汽车.xls'
    inspect_excel_structure(xls_file_path)