import pandas as pd

xls_path = '/Users/jiming/Documents/trae/chanlun-pro/company/理想汽车.xls'
try:
    xls = pd.ExcelFile(xls_path)
    for sheet_name in xls.sheet_names:
        print(f"--- Sheet: {sheet_name} ---")
        df = pd.read_excel(xls, sheet_name=sheet_name)
        print(df.to_string())
except Exception as e:
    print(f"Error reading Excel file: {e}")