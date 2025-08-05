#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单删除向量数据库数据 - 直接删除文件夹
"""

import os
import shutil
import datetime

def delete_vector_db_folder():
    """
    直接删除向量数据库文件夹
    """
    print("=== 删除向量数据库文件夹 ===")
    
    chroma_db_path = "./web/chanlun_chart/chroma_db"
    
    try:
        if os.path.exists(chroma_db_path):
            # 获取文件夹大小信息
            total_size = 0
            file_count = 0
            for dirpath, dirnames, filenames in os.walk(chroma_db_path):
                for filename in filenames:
                    filepath = os.path.join(dirpath, filename)
                    total_size += os.path.getsize(filepath)
                    file_count += 1
            
            print(f"向量数据库路径: {chroma_db_path}")
            print(f"包含文件数: {file_count}")
            print(f"总大小: {total_size / 1024 / 1024:.2f} MB")
            
            # 删除整个文件夹
            shutil.rmtree(chroma_db_path)
            print(f"✅ 成功删除向量数据库文件夹: {chroma_db_path}")
            
            return True
        else:
            print(f"向量数据库文件夹不存在: {chroma_db_path}")
            return True
            
    except Exception as e:
        print(f"❌ 删除向量数据库文件夹失败: {str(e)}")
        return False

def check_vector_db_status():
    """
    检查向量数据库状态
    """
    chroma_db_path = "./web/chanlun_chart/chroma_db"
    
    if os.path.exists(chroma_db_path):
        # 计算文件夹信息
        total_size = 0
        file_count = 0
        for dirpath, dirnames, filenames in os.walk(chroma_db_path):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                total_size += os.path.getsize(filepath)
                file_count += 1
        
        print(f"向量数据库状态: 存在")
        print(f"路径: {chroma_db_path}")
        print(f"文件数: {file_count}")
        print(f"大小: {total_size / 1024 / 1024:.2f} MB")
    else:
        print(f"向量数据库状态: 不存在")
        print(f"路径: {chroma_db_path}")

def main():
    """
    主函数
    """
    print("开始删除向量数据库文件夹...")
    print(f"执行时间: {datetime.datetime.now()}")
    
    # 显示删除前状态
    print("\n=== 删除前状态 ===")
    check_vector_db_status()
    
    # 确认删除操作
    print("\n⚠️  警告: 此操作将完全删除向量数据库文件夹，无法恢复！")
    confirm = input("确认删除向量数据库文件夹？(输入 'yes' 确认): ")
    
    if confirm.lower() != 'yes':
        print("操作已取消")
        return
    
    # 执行删除操作
    success = delete_vector_db_folder()
    
    # 显示删除后状态
    print("\n=== 删除后状态 ===")
    check_vector_db_status()
    
    # 总结
    print("\n=== 删除操作总结 ===")
    if success:
        print("✅ 向量数据库文件夹删除成功")
    else:
        print("❌ 向量数据库文件夹删除失败")
    
    print(f"完成时间: {datetime.datetime.now()}")

if __name__ == "__main__":
    main()