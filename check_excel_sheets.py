#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pandas as pd
import os

def check_excel_sheets():
    """检查Excel文件中的工作表内容"""
    
    excel_files = [
        '/Users/jiming/Documents/trae/chanlun-pro/company/理想汽车.xls',
        '/Users/jiming/Documents/trae/chanlun-pro/company/KH.02015_理想汽车_finance.xls'
    ]
    
    for excel_path in excel_files:
        if not os.path.exists(excel_path):
            print(f"❌ Excel文件不存在: {excel_path}")
            continue
            
        print(f"\n📊 检查Excel文件: {os.path.basename(excel_path)}")
        print("=" * 60)
        
        try:
            xls = pd.ExcelFile(excel_path)
            print(f"工作表列表: {xls.sheet_names}")
            
            for sheet_name in xls.sheet_names:
                print(f"\n📋 **{sheet_name}**")
                print("-" * 40)
                
                # 读取前10行来查看结构
                try:
                    df_preview = pd.read_excel(xls, sheet_name=sheet_name, nrows=10)
                    print(f"  • 数据形状: {df_preview.shape}")
                    print(f"  • 列名: {list(df_preview.columns)[:5]}..." if len(df_preview.columns) > 5 else f"  • 列名: {list(df_preview.columns)}")
                    
                    # 查找包含日期的行
                    date_found = False
                    for idx, row in df_preview.iterrows():
                        row_str = ' '.join([str(val) for val in row.values if pd.notna(val)])
                        if '年' in row_str and '月' in row_str:
                            print(f"  • 找到日期行 (第{idx+1}行): {row_str[:100]}...")
                            date_found = True
                            break
                    
                    if not date_found:
                        print("  • 未找到日期行")
                        
                    # 检查是否是财务报表
                    if any(keyword in sheet_name for keyword in ['资产负债表', '利润表', '现金流量表', '损益表']):
                        print(f"  ✅ 这是财务报表: {sheet_name}")
                    else:
                        print(f"  ❌ 这不是财务报表: {sheet_name}")
                        
                except Exception as e:
                    print(f"  ❌ 读取工作表失败: {str(e)}")
                    
        except Exception as e:
            print(f"❌ 打开Excel文件失败: {str(e)}")

if __name__ == "__main__":
    check_excel_sheets()