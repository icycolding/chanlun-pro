#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
删除数据库中company_financials表的所有数据
"""

import os
import sys
import datetime

# 将项目 src 目录添加到 sys.path
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))

from chanlun.db import db, TableByCompanyFinancials

def delete_all_company_financials():
    """
    删除company_financials表中的所有数据
    """
    try:
        with db.Session() as session:
            # 查询删除前的记录数
            count_before = session.query(TableByCompanyFinancials).count()
            print(f"删除前记录数: {count_before}")
            
            if count_before == 0:
                print("表中没有数据，无需删除")
                return True
            
            # 删除所有记录
            deleted_count = session.query(TableByCompanyFinancials).delete()
            session.commit()
            
            print(f"成功删除 {deleted_count} 条记录")
            
            # 验证删除结果
            count_after = session.query(TableByCompanyFinancials).count()
            print(f"删除后记录数: {count_after}")
            
            if count_after == 0:
                print("✅ 所有财务数据已成功删除")
                return True
            else:
                print(f"⚠️ 删除不完整，仍有 {count_after} 条记录")
                return False
                
    except Exception as e:
        print(f"❌ 删除财务数据时发生错误: {e}")
        return False

def main():
    """
    主函数
    """
    print("开始删除company_financials表中的所有数据...")
    print(f"执行时间: {datetime.datetime.now()}")
    
    # 确认删除操作
    confirm = input("确认要删除所有财务数据吗？(输入 'yes' 确认): ")
    if confirm.lower() != 'yes':
        print("操作已取消")
        return
    
    # 执行删除
    success = delete_all_company_financials()
    
    if success:
        print("\n=== 删除操作完成 ===")
    else:
        print("\n=== 删除操作失败 ===")
        sys.exit(1)

if __name__ == "__main__":
    main()