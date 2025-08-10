#!/usr/bin/env python
# -*- coding:utf-8 -*-
"""
Date: 2021/1/15 16:59
Desc: 个股新闻数据 (GUI Version with Tkinter)
"""
import pandas as pd # 用于处理从某些API返回的数据帧 (例如旧的stock_news_em)

import eikon as ek  # Eikon API库
from datetime import timedelta, datetime, date

from bs4 import BeautifulSoup # 用于从HTML中提取纯文本
import os
import pymysql      # MySQL数据库连接
import time
import schedule     # 用于定时任务
import threading    # 用于在后台运行任务，防止GUI阻塞
import tkinter as tk # Python内置的GUI库
from tkinter import ttk, scrolledtext, messagebox, simpledialog, Frame, Label, Entry, Button, Listbox, Scrollbar, PanedWindow
from tkinter.constants import END, DISABLED, NORMAL, W, E, NSEW, HORIZONTAL, VERTICAL, BOTH, X, Y, LEFT, RIGHT
import queue # 用于线程安全地将数据从后台线程传递到GUI线程
from dotenv import load_dotenv, find_dotenv, set_key # 用于加载和保存.env文件中的配置
import markdown # 用于将HTML转换为纯文本
import requests # 用于发送HTTP请求
import time
# --- Configuration ---
# 加载.env文件 (如果存在)，这允许从文件设置初始API密钥和数据库配置
# find_dotenv() 会尝试在当前目录或父目录中查找 .env 文件
# 如果没有 .env 文件，os.getenv 会使用提供的默认值
load_dotenv(find_dotenv())

# 默认数据库配置，可以被 .env 文件中的值覆盖
DB_CONFIG_DEFAULT = {
    'host': os.getenv("DB_HOST", "localhost"),
    'user': os.getenv("DB_USER", "root"),
    'password': os.getenv("DB_PASSWORD", "11028132s"),  # 请替换为你的安全密码或通过.env设置
    'database': os.getenv("DB_NAME", "news_db"),
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor # 使数据库查询结果为字典形式
}

# 默认数据库配置，可以被 .env 文件中的值覆盖
# DB_CONFIG_DEFAULT = {
#     'host': os.getenv("DB_HOST", "47.103.0.217"),
#     'user': os.getenv("DB_USER", "newapi"),
#     'password': os.getenv("DB_PASSWORD", "19840916newS!"),  # 请替换为你的安全密码或通过.env设置
#     'database': os.getenv("DB_NAME", "news_db"),
#     'charset': 'utf8mb4',
#     'cursorclass': pymysql.cursors.DictCursor # 使数据库查询结果为字典形式
# }
# 全局数据库配置变量，GUI启动时会使用它，理论上也可以让GUI修改它（本例中未实现动态修改DB配置）
DB_CONFIG = DB_CONFIG_DEFAULT.copy()
# print('DB_CONFIG: ', DB_CONFIG)

# API密钥的默认值，会尝试从环境变量加载，否则使用占位符或硬编码的测试值
# 这些StringVar将在GUI类中创建并与输入框绑定
# 直接的全局字符串变量用于非GUI部分或作为GUI StringVar的初始值
# EIKON_API_KEY_GLOBAL = '8105ebb07226418688a41816e04be89b4fb18d39'
EIKON_API_KEY_GLOBAL = '80acba80102b4c6d9a7513b961d7a25e432ec16d'




# --- Global state variables for controlling background tasks and GUI updates ---
stop_scheduler_event = threading.Event()  # 用于通知调度器线程停止
news_fetch_active = threading.Event()     # 控制Eikon新闻获取任务是否执行
scheduler_thread = None                   # 保存调度器线程的引用

gui_queue = queue.Queue() # 线程安全的队列，用于从后台线程向GUI发送更新消息
app_instance = None # 全局引用GUI应用实例，方便其他函数访问（例如日志）


# --- Logging and GUI Update Helper Functions ---
def log_to_gui(message: str, source: str = "SYSTEM"):
    """
    安全地将日志消息发送到GUI的日志区域，并打印到控制台。
    通过gui_queue与GUI主线程通信。
    """
    print(f"DEBUG: log_to_gui called with message: [{source}] {message}") # 新增调试
    global app_instance
    now_str = datetime.now().strftime("%H:%M:%S") # 只用时间，日期在GUI日志中可能显得冗余
    log_entry = f"[{now_str}] [{source.upper()}] {message}"
    print(log_entry) # 仍然打印到控制台以供调试
    if app_instance: # 检查GUI实例是否存在
        gui_queue.put({"type": "log", "message": log_entry})

def update_news_display_list(title: str, pub_time_str: str):
    """
    安全地将获取到的新闻条目发送到GUI的新闻列表区域。
    """
    global app_instance
    if app_instance:
        # pub_time_dt = datetime.fromisoformat(pub_time_iso) # 假设传入的是ISO格式字符串
        # display_text = f"{pub_time_dt.strftime('%m-%d %H:%M')} - {title[:70]}"
        display_text = f"{pub_time_str} - {title[:70]}" # 直接使用传入的格式化时间
        gui_queue.put({"type": "news_item", "text": display_text})


# --- Core API and Database Functions (adapted for GUI logging) ---

def get_db_connection():
    """建立并返回一个MySQL数据库连接。"""
    if not all(DB_CONFIG.get(k) for k in ['host', 'user', 'password', 'database']):
        log_to_gui("数据库配置不完整 (host, user, password, database)。", "DB_ERROR")
        return None
    try:
        connection = pymysql.connect(**DB_CONFIG)
        # log_to_gui("数据库连接成功。", "DB") # 频繁日志，可选
        return connection
    except pymysql.MySQLError as e:
        log_to_gui(f"数据库连接失败: {e}", "DB_ERROR")
        return None

# def get_last_news_time_from_db():
#     """
#     从数据库获取最新新闻的时间
#     """
#     connection = None
#     try:
#         connection = get_db_connection()
#         if not connection:
#             log_to_gui("无法连接数据库，使用默认开始时间", "DB_ERROR")
#             return datetime.now() - timedelta(hours=1)
            
#         with connection.cursor() as cursor:
#             # 尝试从published_at列获取最新时间
#             cursor.execute("SELECT MAX(published_at) as max_time FROM news WHERE published_at IS NOT NULL")
#             result = cursor.fetchone()
            
#             if result and result['max_time']:
#                 last_time = result['max_time']
#                 log_to_gui(f"找到数据库最新新闻时间: {last_time}", "DB")
#                 return last_time
#             else:
#                 # 如果没有数据，默认为1小时前
#                 default_start = datetime.now() - timedelta(hours=1)
#                 log_to_gui(f"数据库中没有新闻数据，使用默认开始时间: {default_start}", "DB")
#                 return default_start
                
#     except Exception as e:
#         log_to_gui(f"获取最新新闻时间出错: {e}", "DB_ERROR")
#         # 出错时默认为1小时前
#         default_start = datetime.now() - timedelta(hours=1)
#         return default_start
#     finally:
#         if connection:
#             connection.close()


  
def get_eikon_news_data(ek_api_key_from_app: str, custom_query: str = None, count: int = 10, 
                        products_tag: str = 'MajorFX', start_date: str = None, end_date: str = None, base_url: str = "http://www.chanlunpro.com/"):
    """从Eikon获取新闻数据。"""
    global EIKON_API_KEY_GLOBAL
    # 如果GUI传入了key，则使用它，否则依赖全局（可能来自.env）
    current_eikon_key = ek_api_key_from_app if ek_api_key_from_app else EIKON_API_KEY_GLOBAL
    print('current_eikon_key: ', current_eikon_key)
    # 
    if not current_eikon_key or current_eikon_key == 'YOUR_EIKON_API_KEY_HERE':
        log_to_gui("Eikon API Key 未配置。跳过 Eikon 新闻获取。", "EIKON")
        return []
    
    log_to_gui("正在尝试设置 Eikon API key...", "EIKON")
    try:
        ek.set_app_key(current_eikon_key)
        log_to_gui("Eikon API key 设置成功。", "EIKON")
    except Exception as e:
        log_to_gui(f"设置 Eikon App Key 时出错: {e}", "EIKON_ERROR")
        return []
    if custom_query:
        all_queries = [q.strip() for q in custom_query.split(',')]
        log_to_gui(f"使用自定义查询: {all_queries}", "EIKON")
    else:
        all_queries = ['Report:TOP/FRX','Topic:FRX','Topic:BRV', 'Report:TOP/DBT', 'Report:TOP/CE', 'Report:TOP/NEWS', 'Report:TOP/CHINA', 'Report:TOP/MTL']
        log_to_gui(f"使用默认查询: {all_queries}", "EIKON")

    all_news_list = []
    for query in all_queries:
        # add language

        fetch_params = {'query': query, 'count': count}
        #
        if start_date: fetch_params['date_from'] = start_date
        if end_date: fetch_params['date_to'] = end_date
        # 确保日期格式正确
        # log_to_gui(f"start_date: {start_date.__class__}, end_date: {end_date}", "EIKON")
        log_to_gui(f"正在使用参数获取 Eikon 新闻标题: {fetch_params}", "EIKON")
        # ek.get_news_headlines(language='en')
        print('fetch_params: ', fetch_params)
        try:
            news_headlines_df = ek.get_news_headlines(**fetch_params)
            print("\n--- DataFrame Info ---") # 添加打印语句
            print(news_headlines_df.info()) # 添加打印语句
            print("\n--- DataFrame Dtypes ---") # 添加打印语句
            print(news_headlines_df.dtypes) # 添加打印语句
            print("\n----------------------") # 添加打印语句
            if news_headlines_df is None:
                log_to_gui("从 Eikon 获取新闻标题失败，返回结果为 None。", "EIKON_ERROR")
                return []
        except Exception as e:
            log_to_gui(f"从 Eikon 获取新闻标题时出错: {str(e)}", "EIKON_ERROR")
            return []

        if news_headlines_df is None or news_headlines_df.empty:
            log_to_gui(f"未从 Eikon 找到关于查询 '{query}' 的新闻标题或返回结果为空。", "EIKON")
            return []

        log_to_gui(f"已获取 {news_headlines_df.shape[0]} 条标题。正在处理...", "EIKON")
        processed_news_list = []
        for index, row in news_headlines_df.iterrows():
            story_id = row.get('storyId')
            version_created = row.get('versionCreated') # pandas Timestamp
            news_text_title = row.get('text', '无标题')

            if not story_id:
                log_to_gui(f"跳过标题（缺少storyId）: {news_text_title[:50]}...", "EIKON")
                continue
            
            try:
                story_html_content = ek.get_news_story(story_id)
                html_for_soup = markdown.markdown(story_html_content) # Markdown -> HTML
                soup = BeautifulSoup(html_for_soup, 'html.parser')
                plain_text_content = soup.get_text(separator=' ', strip=True).replace('\r\n', ' ').replace('\n', ' ')
                
                # 处理pandas Timestamp，确保正确转换为Python datetime
                if pd.notna(version_created):
                    if hasattr(version_created, 'to_pydatetime'):
                        published_dt = version_created.to_pydatetime()
                    else:
                        # 如果是numpy datetime64，先转换为pandas Timestamp
                        published_dt = pd.to_datetime(version_created).to_pydatetime()
                else:
                    published_dt = datetime.now()
                # published_at_sh = published_dt + timedelta(hours=8) if published_dt else datetime.now() + timedelta(hours=8)
                published_at_sh = published_dt
                news_item_data = {
                    "story_id": story_id, "title": news_text_title, "content": plain_text_content,
                    "source": "Eikon/Refinitiv", "relatedProducts": products_tag, 
                    "published_at": published_dt, # Python datetime object
                }
                print('published_at_sh',published_at_sh)
                post_news_data = {
                            'story_id': story_id,
                            'title': news_text_title,
                            'body': plain_text_content,
                            'source': "Eikon/Refinitiv",
                            'published_at': published_at_sh.isoformat() if published_at_sh else '',
                            'language': 'language'
                        }
                # print('start post1111111')
                # 调用POST函数
                posted_count = 0
                all_news_list.append(post_news_data)
              
                # 发送消息到GUI队列以更新新闻列表显示
                update_news_display_list(news_text_title, published_dt.strftime("%Y-%m-%d %H:%M"))
            except Exception as e:
                log_to_gui(f"处理 Eikon storyId {story_id} ('{news_text_title[:30]}...') 时出错: {e}", "EIKON_ERROR")
    print('post_news_data', len(all_news_list))
    
    # 分批上传，每次最多100条
    batch_size = 100
    total_news = len(all_news_list)
    successful_batches = 0
    failed_batches = 0
    
    if total_news > 0:
        log_to_gui(f"准备分批上传 {total_news} 条新闻，每批 {batch_size} 条", "EIKON")
        
        for i in range(0, total_news, batch_size):
            batch = all_news_list[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (total_news + batch_size - 1) // batch_size
            
            log_to_gui(f"正在上传第 {batch_num}/{total_batches} 批，包含 {len(batch)} 条新闻", "EIKON")
            
            if post_news_to_external_api(batch, base_url):
                successful_batches += 1
                log_to_gui(f"第 {batch_num} 批新闻上传成功", "EIKON")
            else:
                failed_batches += 1
                log_to_gui(f"第 {batch_num} 批新闻上传失败", "EIKON_ERROR")
        
        log_to_gui(f"批量上传完成：成功 {successful_batches} 批，失败 {failed_batches} 批", "EIKON")
    else:
        log_to_gui("没有新闻数据需要上传", "EIKON")
            
    processed_news_list.append(news_item_data)
    return processed_news_list

def ensure_db_table(connection, table_name, create_sql, check_columns=None):
    """通用函数，确保表存在，并可选地检查和添加列。"""
    if check_columns is None: check_columns = {}
    db_name = DB_CONFIG['database']
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"SHOW TABLES LIKE '{table_name}';")
            if not cursor.fetchone():
                log_to_gui(f"表 '{table_name}' 不存在。正在创建...", "DB_SETUP")
                cursor.execute(create_sql)
                log_to_gui(f"表 '{table_name}' 创建成功。", "DB_SETUP")
            else:
                log_to_gui(f"表 '{table_name}' 已存在。检查列...", "DB_SETUP")
                for col_name, col_definition in check_columns.items():
                    cursor.execute(f"""
                        SELECT COUNT(*) as col_exists FROM information_schema.columns
                        WHERE table_schema = '{db_name}' AND table_name = '{table_name}' AND column_name = '{col_name}';
                    """)
                    if cursor.fetchone()['col_exists'] == 0:
                        log_to_gui(f"列 '{col_name}' 在表 '{table_name}' 中不存在。正在添加...", "DB_SETUP")
                        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_definition};")
                        log_to_gui(f"列 '{col_name}' 已添加到 '{table_name}'。", "DB_SETUP")
        connection.commit()
    except pymysql.MySQLError as e:
        log_to_gui(f"确保表 '{table_name}' 时出错: {e}", "DB_ERROR")
        connection.rollback()


def ensure_all_tables_exist():
    """确保所有需要的数据库表都存在并具有正确的结构。"""
    log_to_gui("开始检查/创建数据库表...", "DB_SETUP")
    conn = get_db_connection()
    if not conn:
        log_to_gui("无法连接到数据库以检查表结构。", "DB_ERROR")
        return

    # 1. news 表
    create_news_table_sql = """
    CREATE TABLE news (
        id INT AUTO_INCREMENT PRIMARY KEY,
        story_id VARCHAR(255) NULL COMMENT '来自Eikon或其他源的唯一故事ID',
        title VARCHAR(500) NOT NULL,
        content TEXT,
        source VARCHAR(100),
        relatedProducts VARCHAR(255) COMMENT '例如 USDCNH, MajorFX',
        published_at DATETIME COMMENT '实际发布时间',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '记录插入数据库的时间',
        UNIQUE KEY `story_id_unique` (`story_id`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """
    # news 表的列检查 (如果表已存在，确保 story_id 和其唯一约束存在)
    # 为简化，这里只做表创建，假设 story_id 结构是随表创建的
    ensure_db_table(conn, "news", create_news_table_sql)


    
    if conn:
        conn.close()
    log_to_gui("数据库表检查/创建完成。", "DB_SETUP")


def insert_news_data_into_db(news_data_list: list):
    """将新闻数据列表插入数据库，跳过已存在的 story_id。"""
    if not news_data_list:
        log_to_gui("没有新闻数据需要插入。", "DB")
        return 0, 0
    conn = get_db_connection()
    if not conn: return 0, 0
    inserted_count, skipped_count = 0, 0
    print('insert_news_data_into_db: ', inserted_count)
    
    try:
        with conn.cursor() as cursor:
            for news_item in news_data_list:
                story_id_to_check = news_item.get("story_id")
                if not story_id_to_check:
                    log_to_gui(f"跳过新闻（缺少story_id）: {news_item.get('title', 'N/A')[:30]}...", "DB")
                    skipped_count += 1
                    continue
                
                # 预检查以减少日志中的重复键错误 (数据库的UNIQUE约束是最终防线)
                cursor.execute("SELECT 1 FROM news WHERE story_id = %s", (story_id_to_check,))
                if cursor.fetchone():
                    # log_to_gui(f"StoryId '{story_id_to_check}' 已存在 (预检查)。跳过。", "DB_DEBUG") # 可选的详细日志
                    skipped_count += 1
                    continue
                
                published_at = news_item.get("published_at") # 这是Python datetime对象
                published_at_sh = published_at + timedelta(hours=8) if published_at else datetime.now() + timedelta(hours=8)
                
                insert_sql = """
                INSERT INTO news (story_id, title, content, source, published_at, relatedProducts)
                VALUES (%s, %s, %s, %s, %s, %s)
                """
                try:
                    cursor.execute(insert_sql, (
                        story_id_to_check, news_item.get("title", "No Title"),
                        news_item.get("content", ""), news_item.get("source", "Unknown"),
                        published_at_sh, news_item.get("relatedProducts", "")
                    ))
                    inserted_count += 1
                except pymysql.MySQLError as insert_err:
                    if insert_err.args[0] == 1062: # Duplicate entry for key 'story_id_unique'
                        # log_to_gui(f"StoryId '{story_id_to_check}' 已存在 (数据库约束)。跳过。", "DB_DEBUG")
                        skipped_count += 1
                    else:
                        log_to_gui(f"插入storyId {story_id_to_check}时数据库错误: {insert_err}", "DB_ERROR")
                        skipped_count += 1
            conn.commit()
    except pymysql.MySQLError as e:
        log_to_gui(f"数据库连接或操作错误: {e}", "DB_ERROR")
        if conn: conn.rollback()
    finally:
        if conn: conn.close()
    
    if inserted_count > 0: log_to_gui(f"成功插入 {inserted_count} 条新新闻。", "DB")
    if skipped_count > 0: log_to_gui(f"跳过了 {skipped_count} 条新闻 (已存在或错误)。", "DB")
    if inserted_count == 0 and skipped_count == 0 and news_data_list:
        log_to_gui(f"没有新的新闻被插入。所有条目可能已存在或处理时出错。", "DB")
    return inserted_count, skipped_count


def generate_and_store_daily_summaries(target_date: date):
    """为指定日期生成每日新闻摘要并存储/更新到数据库。"""
    log_to_gui(f"开始为日期 {target_date.isoformat()} 生成每日新闻摘要...", "SUMMARY")
    conn = get_db_connection()
    if not conn: return
    
    try:
        with conn.cursor() as cursor:
            # 1. 获取该日期所有新闻中不同的 relatedProducts
            # 注意：数据库中的 published_at 是UTC+8 (上海时间)
            # target_date 是本地日期，需要确保比较时时区一致或不比较时区部分
            sql_get_products = "SELECT DISTINCT relatedProducts FROM news WHERE DATE(published_at - INTERVAL 8 HOUR) = %s;"
            cursor.execute(sql_get_products, (target_date,))
            product_rows = cursor.fetchall()
            
            if not product_rows:
                log_to_gui(f"在 {target_date.isoformat()} 未找到用于产品摘要的新闻。", "SUMMARY")
                return

            distinct_products = [row['relatedProducts'] for row in product_rows if row['relatedProducts']]
            log_to_gui(f"在 {target_date.isoformat()} 找到的产品: {distinct_products}", "SUMMARY")

            for product_tag in distinct_products:
                if not product_tag: continue
                log_to_gui(f"正在为产品处理摘要: {product_tag} on {target_date.isoformat()}", "SUMMARY")

                sql_get_news = "SELECT title, LEFT(content, 500) as short_content FROM news WHERE DATE(published_at - INTERVAL 8 HOUR) = %s AND relatedProducts = %s ORDER BY published_at DESC LIMIT 20;"
                cursor.execute(sql_get_news, (target_date, product_tag))
                news_items = cursor.fetchall()

                if not news_items:
                    log_to_gui(f"未找到产品 {product_tag} 在 {target_date.isoformat()} 的新闻进行摘要。", "SUMMARY")
                    continue

                news_texts = [f"标题: {item['title']}\n内容摘要: {item['short_content']}\n---" for item in news_items]
                combined_news_text = "\n\n".join(news_texts)
                
                prompt = (
                    f"请根据以下关于“{product_tag}”在 {target_date.strftime('%Y年%m月%d日')} 的新闻：\n\n"
                    f"{combined_news_text}\n\n"
                    f"请对这些新闻进行分类总结，重点突出主要的市场动态、事件或趋势。总结应清晰、简洁，并针对“{product_tag}”这一品种。"
                    f"如果新闻量很少或信息不足，请指出。输出格式为纯文本。"
                )

                summary_text = call_deepseek_api(prompt, model=DEEPSEEK_MODEL)
                log_to_gui(f'LLM 为 {product_tag} 生成的摘要 (前100字符): {summary_text[:100] if summary_text else "None"}...', "SUMMARY_LLM")

                if summary_text:
                    sql_upsert = """
                    INSERT INTO daily_news_summary (summary_date, product_tag, summary_text, model_used, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, NOW(), NOW())
                    ON DUPLICATE KEY UPDATE
                        summary_text = VALUES(summary_text), model_used = VALUES(model_used), updated_at = NOW(); 
                    """
                    try:
                        cursor.execute(sql_upsert, (target_date, product_tag, summary_text, DEEPSEEK_MODEL))
                        if cursor.rowcount == 1: log_to_gui(f"已插入产品 {product_tag} 在 {target_date.isoformat()} 的摘要。", "SUMMARY_DB")
                        elif cursor.rowcount >= 2: log_to_gui(f"已更新产品 {product_tag} 在 {target_date.isoformat()} 的摘要。", "SUMMARY_DB") # MySQL ON DUP UPDATE for actual update returns 2
                        else: log_to_gui(f"产品 {product_tag} 在 {target_date.isoformat()} 的摘要已是最新。", "SUMMARY_DB")
                    except pymysql.MySQLError as db_err:
                         log_to_gui(f"为 {product_tag} 更新/插入摘要时数据库错误: {db_err}", "SUMMARY_DB_ERROR")
                else:
                    log_to_gui(f"未能为产品 {product_tag} 在 {target_date.isoformat()} 从LLM生成摘要。", "SUMMARY_LLM_ERROR")
        if conn: conn.commit()
    except pymysql.MySQLError as e:
        log_to_gui(f"为日期 {target_date.isoformat()} 处理每日摘要时数据库错误: {e}", "SUMMARY_DB_ERROR")
        if conn: conn.rollback()
    except Exception as e:
        log_to_gui(f"为日期 {target_date.isoformat()} 处理每日摘要时发生意外错误: {e}", "SUMMARY_ERROR")
        if conn: conn.rollback()
    finally:
        if conn: conn.close()
    log_to_gui(f"日期 {target_date.isoformat()} 的每日新闻摘要处理完成。", "SUMMARY")


# --- Functions to be run by scheduler (wrapper for GUI control) ---
def scheduled_eikon_news_job_wrapper(app_ref):
    """由 schedule 调用，检查 news_fetch_active 标志。"""
    if news_fetch_active.is_set() and app_ref:
        log_to_gui("定时 Eikon 新闻任务正在运行...", "SCHEDULER")
        
        # 获取数据库中最后一条新闻的时间
        # last_news_time = get_last_news_time_from_db()
        current_time = datetime.now()
        
        # # 计算时间差
        # time_diff = current_time - last_news_time + timedelta(hours=8)  
        
        # # 根据时间差决定获取新闻的数量
        # if time_diff.total_seconds() > 12* 3600:  # 超过1天
        #     news_count = 200
        #     log_to_gui(f"距离上次新闻超过1天 ({time_diff}), 获取200条新闻", "SCHEDULER")
        # else:
        #     news_count = 10
        #     log_to_gui(f"距离上次新闻不足1天 ({time_diff}), 获取10条新闻", "SCHEDULER")
        
        # # 设置时间范围：从最后一条新闻时间到现在
        # effective_start_date = last_news_time
        # log_to_gui(f"最后一条新闻时间: {last_news_time},{effective_start_date.__class__}", "SCHEDULER")
        # effective_end_date = current_time
        
        # log_to_gui(f"新闻获取时间范围: {effective_start_date} 到 {effective_end_date}", "SCHEDULER")
        
        # eikon_api_key_to_use = app_ref.eikon_api_key_var.get() # 从GUI获取当前Key
        # log_to_gui(f"使用的Eikon API Key: {eikon_api_key_to_use[:5]}...", "SCHEDULER")
        # #datetime.datetime to %Y-%m-%dT%H:%M:%SZ'
        # s_date = effective_start_date.strftime('%Y-%m-%dT%H:%M:%SZ') if effective_start_date else None
        # e_date = effective_end_date.strftime('%Y-%m-%dT%H:%M:%SZ') if effective_end_date else None
        # # 调用获取新闻的函数
        # # print('s_date',s_date)
        # # print('e_date',e_date)
        # # try:
        # # s_date = datetime.strptime(str(effective_start_date), '%Y-%m-%d %H:%M').strftime('%Y-%m-%dT%H:%M:%SZ') if start_str else None
        # # e_date = datetime.strptime(str(effective_end_date), '%Y-%m-%d %H:%M').strftime('%Y-%m-%dT%H:%M:%SZ') if end_str else None
        # # s_date = effective_start_date.strftime('%Y-%m-%dT%H:%M:%SZ') if effective_start_date else None
        # # e_date = effective_end_date.strftime('%Y-%m-%dT%H:%M:%SZ') if effective_end_date else None
        # print('s_date',s_date,s_date.__class__)
        # # except ValueError:
        # #     messagebox.showerror("日期格式错误", "日期时间格式应为 YYYY-MM-DD HH:MM。")
        #     # return
        # 格式化日期为ISO字符串
        # start_date_iso = effective_start_date.strftime("%Y-%m-%d %H:%M:%S")
        # end_date_iso = effective_end_date.strftime("%Y-%m-%d %H:%M:%S")
        # start_date_iso = s_date
        # end_date_iso = e_date
        # 从GUI获取BASE_URL
        current_base_url = app_ref.base_url_var.get() if app_ref else "http://www.chanlunpro.com/"
        run_eikon_news_pipeline_task( # 调用实际的任务执行函数
            ek_api_key=eikon_api_key_to_use,
            count_val=str(news_count),
            base_url=current_base_url
        )
    else:
        log_to_gui("定时 Eikon 新闻任务跳过 (未激活或无App实例)。", "SCHEDULER")



def run_eikon_news_pipeline_task(ek_api_key, start_date_iso=None, end_date_iso=None, count_val="10", base_url="http://www.chanlunpro.com/", custom_query=None):
    """实际执行Eikon新闻获取和存储的函数 (被手动或定时任务调用)。"""
    log_to_gui("Eikon 新闻管道任务开始...", "PIPELINE")
    try:
        # 确保 count_val 被正确转换为整数，如果无效则默认为 10
        try:
            count = int(count_val)
        except (ValueError, TypeError):
            count = 10
            log_to_gui(f"无效的新闻数量值 '{count_val}'，将使用默认值 10。", "PIPELINE_WARNING")
        
        log_to_gui(f"获取新闻从 {start_date_iso or '默认开始'} 到 {end_date_iso or '现在'} (数量: {count})", "PIPELINE")
        eikon_news_items = get_eikon_news_data(
            ek_api_key_from_app=ek_api_key, # 使用传入的key
            custom_query=custom_query,
            count=count, # 使用转换后的整数值
            start_date=start_date_iso,
            end_date=end_date_iso,
            products_tag="MajorFX",
            base_url=base_url
        )
        # print('eikon_news_items',eikon_news_items)
        # if eikon_news_items:
        #     insert_news_data_into_db(eikon_news_items)
        #     # 新增：将新闻内容也显示到GUI
        #     for item in eikon_news_items:
        #         gui_queue.put({"type": "news_item", "text": f"[{item.get('published_at','')}] {item.get('title','')}\n{item.get('content','')}"})
        # else:
        #     log_to_gui("未从Eikon获取到新新闻或处理时发生问题。", "PIPELINE")
    except Exception as e:
        log_to_gui(f"Eikon 新闻管道任务发生严重错误: {e}", "PIPELINE_ERROR")
    finally:
        log_to_gui("Eikon 新闻管道任务完成。", "PIPELINE")


def run_scheduler_loop():
    """在单独线程中运行 schedule.run_pending() 循环。"""
    global app_instance # 需要 app_instance 来调用包装函数
    log_to_gui("调度器线程已启动。", "SCHEDULER")
    
    # 清除旧的作业（如果有）并重新计划
    schedule.clear() 
    
    # 定时获取新闻 (例如每10分钟)
    # lambda 中传递 app_instance 以便包装函数可以访问GUI的StringVar
    schedule.every(1).minutes.do(scheduled_eikon_news_job_wrapper, app_ref=app_instance)
    log_to_gui(f"Eikon 新闻任务已计划每10分钟运行一次。", "SCHEDULER")


    while not stop_scheduler_event.is_set():
        schedule.run_pending()
        time.sleep(1) # 每秒检查一次是否有待处理任务
    
    log_to_gui("调度器线程已停止。", "SCHEDULER")
    schedule.clear() # 线程停止时清除所有作业


# --- GUI Application Class ---
class NewsAppGUI(tk.Tk): # 让主应用类继承 tk.Tk
    def __init__(self):
        super().__init__() # 初始化 tk.Tk 基类
        self.title("新闻与摘要工具 v1.0")
        self.geometry("850x750") # 稍微调整尺寸

        global app_instance, EIKON_API_KEY_GLOBAL, DEEPSEEK_API_KEY_GLOBAL
        app_instance = self # 设置全局GUI实例引用

        # --- Tkinter StringVars for API keys and date inputs ---
        self.eikon_api_key_var = tk.StringVar(value=EIKON_API_KEY_GLOBAL)
        # self.deepseek_api_key_var = tk.StringVar(value=DEEPSEEK_API_KEY_GLOBAL)
        
        # 用于新闻获取的时间范围
        self.news_start_date_var = tk.StringVar(value=(datetime.now() - timedelta(hours=2)).strftime('%Y-%m-%d %H:%M'))
        self.news_end_date_var = tk.StringVar(value=datetime.now().strftime('%Y-%m-%d %H:%M'))
        self.news_count_var = tk.StringVar(value="10") # 新闻获取数量

        # GUI 控件的变量
        self.eikon_api_key_var = tk.StringVar()
        self.news_start_date_var = tk.StringVar()
        self.news_end_date_var = tk.StringVar()
        self.news_count_var = tk.StringVar(value="10") # 默认获取10条
        self.custom_query_var = tk.StringVar(value="")  # 新增自定义查询变量

        # 使用从 .env 加载的全局变量初始化 StringVar
        self.eikon_api_key_var.set(EIKON_API_KEY_GLOBAL)
        
        # BASE_URL 选择变量
        self.base_url_var = tk.StringVar(value="http://www.chanlunpro.com/")

        # 跟踪GUI是否仍在运行
        self.is_gui_running = True

        self._setup_styles()
        self._create_widgets()
        
        # 在GUI启动时尝试加载一次API Keys (如果.env存在)
        # StringVars已经通过os.getenv在上面初始化了

        # 确保数据库表存在 (在后台线程执行以避免阻塞GUI启动)
        # log_to_gui("应用启动，正在后台检查数据库表...", "APP_INIT")
        # threading.Thread(target=ensure_all_tables_exist, daemon=True).start()
        
        self.process_gui_queue() # 启动GUI消息队列处理器
        self.protocol("WM_DELETE_WINDOW", self.on_closing) # 处理窗口关闭事件

    def _setup_styles(self):
        """配置现代化的ttk控件样式。"""
        self.style = ttk.Style(self)
        self.style.theme_use('clam')
        
        # 现代化配色方案
        primary_color = "#2563eb"      # 蓝色主色调
        secondary_color = "#64748b"    # 灰色辅助色
        success_color = "#10b981"      # 绿色成功色
        danger_color = "#ef4444"       # 红色危险色
        bg_color = "#f8fafc"           # 浅灰背景色
        text_color = "#1e293b"         # 深色文字
        
        # 按钮样式 - 使用支持中文的字体
        self.style.configure("Modern.TButton", 
                           padding=(12, 8), 
                           relief="flat", 
                           font=('SimHei', 10, 'normal'),
                           borderwidth=1)
        
        self.style.configure("Primary.TButton", 
                           foreground="white", 
                           background=primary_color,
                           focuscolor="none",
                           borderwidth=0)
        self.style.map("Primary.TButton", 
                      background=[('active', '#1d4ed8'), ('pressed', '#1e40af')])
        
        self.style.configure("Success.TButton", 
                           foreground="white", 
                           background=success_color,
                           focuscolor="none",
                           borderwidth=0)
        self.style.map("Success.TButton", 
                      background=[('active', '#059669'), ('pressed', '#047857')])
        
        self.style.configure("Danger.TButton", 
                           foreground="white", 
                           background=danger_color,
                           focuscolor="none",
                           borderwidth=0)
        self.style.map("Danger.TButton", 
                      background=[('active', '#dc2626'), ('pressed', '#b91c1c')])
        
        # 标签样式 - 使用支持中文的字体
        self.style.configure("Title.TLabel", 
                           font=('SimHei', 16, 'bold'), 
                           foreground=text_color,
                           padding=(0, 10, 0, 15))
        
        self.style.configure("Heading.TLabel", 
                           font=('SimHei', 12, 'bold'), 
                           foreground=text_color,
                           padding=(0, 5, 0, 5))
        
        self.style.configure("Body.TLabel", 
                           font=('SimHei', 10), 
                           foreground=secondary_color)
        
        # 输入框样式 - 使用支持中文的字体
        self.style.configure("Modern.TEntry", 
                           padding=(10, 8), 
                           font=('SimHei', 10),
                           fieldbackground="white",
                           borderwidth=1,
                           relief="solid")
        
        # 框架样式
        self.style.configure("TLabelFrame", 
                           relief="solid",
                           borderwidth=1,
                           background="white")
        self.style.configure("TLabelFrame.Label", 
                           font=('SimHei', 11, 'bold'),
                           foreground=text_color,
                           background="white")
        
        # 卡片样式
        self.style.configure("Card.TLabelFrame", 
                           relief="solid",
                           borderwidth=1,
                           background="white",
                           padding=15)
        self.style.configure("Card.TLabelFrame.Label", 
                           font=('SimHei', 11, 'bold'),
                           foreground=text_color,
                           background="white")
        
        # Notebook样式
        self.style.configure("Modern.TNotebook", 
                           tabposition="n",
                           borderwidth=0)
        self.style.configure("Modern.TNotebook.Tab", 
                           padding=(20, 10),
                           font=('SimHei', 10, 'normal'))

    def _create_widgets(self):
        """创建现代化的GUI界面布局。"""
        # 设置主窗口背景色
        self.configure(bg='#f8fafc')
        
        # 创建主容器
        main_container = ttk.Frame(self)
        main_container.pack(fill=BOTH, expand=True, padx=20, pady=20)
        
        # 标题区域
        title_frame = ttk.Frame(main_container)
        title_frame.pack(fill=X, pady=(0, 20))
        
        title_label = ttk.Label(title_frame, text="Eikon 新闻数据管理系统", style="Title.TLabel")
        title_label.pack(side=LEFT)
        
        # 状态指示器
        self.status_frame = ttk.Frame(title_frame)
        self.status_frame.pack(side=RIGHT)
        
        self.status_label = ttk.Label(self.status_frame, text="● 就绪", style="Body.TLabel")
        self.status_label.pack(side=RIGHT, padx=(10, 0))
        
        # 主内容区域 - 使用网格布局
        content_frame = ttk.Frame(main_container)
        content_frame.pack(fill=BOTH, expand=True)
        content_frame.grid_columnconfigure(1, weight=1)
        content_frame.grid_rowconfigure(1, weight=1)
        
        # 左侧控制面板
        control_panel = ttk.Frame(content_frame)
        control_panel.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 15))
        control_panel.grid_propagate(False)
        control_panel.configure(width=320)
        
        # 右上角 - 新闻显示区域
        news_panel = ttk.Frame(content_frame)
        news_panel.grid(row=0, column=1, sticky="nsew", pady=(0, 10))
        
        # 右下角 - 日志显示区域
        log_panel = ttk.Frame(content_frame)
        log_panel.grid(row=1, column=1, sticky="nsew")
        
        # 创建各个区域的内容
        self._create_control_panel(control_panel)
        self._create_news_panel(news_panel)
        self._create_log_panel(log_panel)
        
    def _create_control_panel(self, parent):
         """创建左侧控制面板。"""
         # API Keys 配置卡片
         api_card = ttk.LabelFrame(parent, text="API 密钥配置", padding=15)
         api_card.pack(fill=X, pady=(0, 15))
         api_card.columnconfigure(1, weight=1)
         
         # Eikon API Key
         ttk.Label(api_card, text="Eikon API Key:", style="Body.TLabel").grid(row=0, column=0, sticky=W, pady=(0, 5))
         eikon_entry = ttk.Entry(api_card, textvariable=self.eikon_api_key_var, style="Modern.TEntry", show="*")
         eikon_entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 10))
         
         # BASE_URL 选择
         ttk.Label(api_card, text="BASE_URL:", style="Body.TLabel").grid(row=2, column=0, sticky=W, pady=(0, 5))
         base_url_combo = ttk.Combobox(api_card, textvariable=self.base_url_var, style="Modern.TCombobox", state="readonly")
         base_url_combo['values'] = ("http://www.chanlunpro.com/", "http://127.0.0.1:9901")
         base_url_combo.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 10))
         
         # 保存按钮
         save_btn = ttk.Button(api_card, text="保存到 .env", command=self.save_api_keys_to_env, style="Modern.TButton")
         save_btn.grid(row=4, column=1, sticky=E)
         
         # 新闻获取配置卡片
         news_card = ttk.LabelFrame(parent, text="新闻获取配置", padding=15)
         news_card.pack(fill=X, pady=(0, 15))
         news_card.columnconfigure(1, weight=1)
         
         # --- 日期时间输入 ---
         ttk.Label(news_card, text="开始时间:", style="Body.TLabel").grid(row=0, column=0, sticky=W, pady=(0, 5))
         start_frame = ttk.Frame(news_card)
         start_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 10))
         start_frame.columnconfigure(0, weight=1)
         start_entry = ttk.Entry(start_frame, textvariable=self.news_start_date_var, style="Modern.TEntry")
         start_entry.grid(row=0, column=0, sticky="ew", padx=(0, 5))
         ttk.Button(start_frame, text="昨天", command=lambda: self.set_datetime_yesterday(self.news_start_date_var), style="Modern.TButton").grid(row=0, column=1)

         ttk.Label(news_card, text="结束时间:", style="Body.TLabel").grid(row=2, column=0, sticky=W, pady=(0, 5))
         end_frame = ttk.Frame(news_card)
         end_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 10))
         end_frame.columnconfigure(0, weight=1)
         end_entry = ttk.Entry(end_frame, textvariable=self.news_end_date_var, style="Modern.TEntry")
         end_entry.grid(row=0, column=0, sticky="ew", padx=(0, 5))
         ttk.Button(end_frame, text="现在", command=lambda: self.set_datetime_now(self.news_end_date_var), style="Modern.TButton").grid(row=0, column=1)

         # --- 自定义查询和数量 ---
         ttk.Label(news_card, text="自定义查询:", style="Body.TLabel").grid(row=4, column=0, columnspan=2, sticky=W, pady=(5, 5))
         query_entry = ttk.Entry(news_card, textvariable=self.custom_query_var, style="Modern.TEntry")
         query_entry.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(0, 10))

         ttk.Label(news_card, text="获取数量:", style="Body.TLabel").grid(row=6, column=0, sticky=W, pady=(0, 5))
         count_entry = ttk.Entry(news_card, textvariable=self.news_count_var, style="Modern.TEntry", width=10)
         count_entry.grid(row=7, column=0, sticky=W, pady=(0, 15))

         # --- 操作按钮 ---
         self.fetch_now_button = ttk.Button(news_card, text="立即获取新闻", style="Primary.TButton")
         self.fetch_now_button.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(5, 10))
         self.fetch_now_button.bind("<Button-1>", lambda event: self.run_eikon_news_once_gui_threaded())

         self.toggle_news_button = ttk.Button(news_card, text="启动定时获取", style="Success.TButton")
         self.toggle_news_button.grid(row=9, column=0, columnspan=2, sticky="ew")
         self.toggle_news_button.bind("<Button-1>", lambda event: self.toggle_news_fetching_schedule())
        
    def _create_news_panel(self, parent):
        """创建新闻显示面板。"""
        # 新闻列表标题
        header_frame = ttk.Frame(parent)
        header_frame.pack(fill=X, pady=(0, 10))
        
        ttk.Label(header_frame, text="获取的新闻", style="Heading.TLabel").pack(side=LEFT)
        
        # 清空按钮
        clear_btn = ttk.Button(header_frame, text="清空列表", command=self.clear_news_list, style="Modern.TButton")
        clear_btn.pack(side=RIGHT)
        
        # 新闻列表容器
        list_frame = ttk.Frame(parent)
        list_frame.pack(fill=BOTH, expand=True)
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)
        
        # 新闻列表
        self.news_listbox = Listbox(list_frame, font=('Helvetica', 10), selectmode=tk.SINGLE, 
                                   relief="flat", borderwidth=1, highlightthickness=0)
        self.news_listbox.grid(row=0, column=0, sticky="nsew")
        
        # 滚动条
        news_scrollbar = Scrollbar(list_frame, orient=VERTICAL, command=self.news_listbox.yview)
        news_scrollbar.grid(row=0, column=1, sticky="ns")
        self.news_listbox.configure(yscrollcommand=news_scrollbar.set)
         
    def _create_log_panel(self, parent):
        """创建日志显示面板。"""
        # 日志标题
        header_frame = ttk.Frame(parent)
        header_frame.pack(fill=X, pady=(0, 10))
        
        ttk.Label(header_frame, text="运行日志", style="Heading.TLabel").pack(side=LEFT)
        
        # 清空日志按钮
        clear_log_btn = ttk.Button(header_frame, text="清空日志", command=self.clear_log, style="Modern.TButton")
        clear_log_btn.pack(side=RIGHT)
        
        # 日志文本区域
        self.log_text_area = scrolledtext.ScrolledText(parent, wrap=tk.WORD, state=DISABLED, 
                                                      font=('Monaco', 9), relief="flat", 
                                                      borderwidth=1, highlightthickness=0)
        self.log_text_area.pack(fill=BOTH, expand=True)
        
    def clear_news_list(self):
        """清空新闻列表。"""
        self.news_listbox.delete(0, END)
        log_to_gui("新闻列表已清空。", "GUI_ACTION")
        
    def clear_log(self):
        """清空日志区域。"""
        self.log_text_area.config(state=NORMAL)
        self.log_text_area.delete(1.0, END)
        self.log_text_area.config(state=DISABLED)
        log_to_gui("日志已清空。", "GUI_ACTION")
        
    def set_datetime_now(self, string_var: tk.StringVar):
        """将指定的StringVar设置为当前日期和时间 (YYYY-MM-DD HH:MM)。"""
        string_var.set(datetime.now().strftime("%Y-%m-%d %H:%M"))

    def set_datetime_yesterday(self, string_var: tk.StringVar):
        """将指定的StringVar设置为前一天的日期和时间 (YYYY-MM-DD HH:MM)。"""
        string_var.set((datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M"))

    def update_api_keys_from_gui(self):
        """从GUI输入框更新全局API Key变量。"""
        global EIKON_API_KEY_GLOBAL
        EIKON_API_KEY_GLOBAL = self.eikon_api_key_var.get()
        # log_to_gui("API Keys in global vars updated from GUI.", "GUI_DEBUG") # 频繁日志

    def save_api_keys_to_env(self):
        """将GUI中当前的API Keys保存到.env文件。"""
        self.update_api_keys_from_gui() # 先确保全局变量是最新的
        env_file_path = find_dotenv()
        if not env_file_path: # 如果 .env 文件不存在，在当前工作目录创建
            env_file_path = os.path.join(os.getcwd(), ".env")
            log_to_gui(f"未找到 .env 文件，将在 {env_file_path} 创建。", "ENV_SAVE")
        
        try:
            # 使用 python-dotenv 的 set_key 来写入或更新 .env 文件
            set_key(env_file_path, "EIKON_API_KEY", EIKON_API_KEY_GLOBAL)
            log_to_gui(f"API Keys 已保存到: {env_file_path}", "ENV_SAVE")
            messagebox.showinfo("保存成功", f"API Keys 已保存到 {os.path.basename(env_file_path)}")
        except Exception as e:
            log_to_gui(f"保存 API Keys 到 .env 时出错: {e}", "ENV_SAVE_ERROR")
            messagebox.showerror("保存失败", f"保存 API Keys 失败: {e}")

    def _validate_keys_for_action(self, action_type="news"):
        """验证特定操作所需的API keys是否已设置。"""
        self.update_api_keys_from_gui() # 确保使用当前输入框的值
        if action_type == "news":
            if not EIKON_API_KEY_GLOBAL or EIKON_API_KEY_GLOBAL == 'YOUR_EIKON_API_KEY_HERE':
                messagebox.showerror("API Key 错误", "请输入有效的 Eikon API Key。")
                return False
        elif action_type == "summary":
            if not DEEPSEEK_API_KEY_GLOBAL or DEEPSEEK_API_KEY_GLOBAL == "YOUR_DEEPSEEK_API_KEY_HERE":
                messagebox.showerror("API Key 错误", "请输入有效的 DeepSeek API Key。")
                return False
        return True

    def run_eikon_news_once_gui_threaded(self):
        """GUI回调：手动触发一次Eikon新闻获取任务（在线程中）。"""
        print("DEBUG: run_eikon_news_once_gui_threaded called") # Debug print
        if not self._validate_keys_for_action("news"):
            print("DEBUG: API Key validation failed.") # Debug print
            return
        print("DEBUG: API Key validation passed. Attempting to start thread.") # Debug print
        
        start_str = self.news_start_date_var.get()
        end_str = self.news_end_date_var.get()
        count_str = self.news_count_var.get()
        
        # 简单的日期格式验证
        try:
            s_date = datetime.strptime(start_str, '%Y-%m-%d %H:%M').strftime('%Y-%m-%dT%H:%M:%SZ') if start_str else None
            e_date = datetime.strptime(end_str, '%Y-%m-%d %H:%M').strftime('%Y-%m-%dT%H:%M:%SZ') if end_str else None
        except ValueError:
            messagebox.showerror("日期格式错误", "日期时间格式应为 YYYY-MM-DD HH:MM。")
            return
            
        log_to_gui(f"手动触发 Eikon 新闻获取 (数量: {count_str}, 开始: {s_date or '默认'}, 结束: {e_date or '默认'})...", "GUI_ACTION")
        # 使用从 GUI 获取的 Eikon Key 和 BASE_URL
        current_eikon_key = self.eikon_api_key_var.get()
        current_base_url = self.base_url_var.get()
        custom_query = self.custom_query_var.get()
        
        # 在新线程中运行新闻获取管道
        thread = threading.Thread(target=run_eikon_news_pipeline_task, 
                                  args=(current_eikon_key, s_date, e_date, count_str, current_base_url, custom_query))
        thread.daemon = True
        thread.start()


    def toggle_news_fetching_schedule(self):
        """GUI回调：启动或暂停定时新闻获取。"""
        if not self._validate_keys_for_action("news"): return

        if news_fetch_active.is_set(): # 如果当前是激活的，则暂停它
            news_fetch_active.clear()
            self.toggle_news_button.config(text="启动定时获取", style="Success.TButton")
            self.status_label.config(text="● 已停止", foreground="#ef4444")
            log_to_gui("定时新闻获取已暂停。", "GUI_CONTROL")
        else: # 如果当前是暂停的，则启动它
            news_fetch_active.set()
            self.toggle_news_button.config(text="停止定时获取", style="Danger.TButton")
            self.status_label.config(text="● 运行中", foreground="#10b981")
            log_to_gui("定时新闻获取已启动。", "GUI_CONTROL")
            # 立即获取一次新闻
            self.run_eikon_news_once_gui_threaded()
            # 如果主调度器未运行，则启动它
            if scheduler_thread is None or not scheduler_thread.is_alive():
                self.start_scheduler_thread_if_needed()
    

    def start_scheduler_thread_if_needed(self):
        """如果调度器线程未运行，则启动它。"""
        global scheduler_thread
        if scheduler_thread is None or not scheduler_thread.is_alive():
            log_to_gui("主调度器未运行，正在启动...", "SCHEDULER")
            stop_scheduler_event.clear() # 确保停止事件被清除
            scheduler_thread = threading.Thread(target=run_scheduler_loop, daemon=True)
            scheduler_thread.start()
        else:
            log_to_gui("主调度器已在运行。", "SCHEDULER_DEBUG")


    def process_gui_queue(self):
        """定期从队列中获取消息并更新GUI。"""
        try:
            while True: # 处理队列中所有当前消息
                message_data = gui_queue.get_nowait() # 非阻塞获取
                print(f"DEBUG: Message received from queue: {message_data.get('type')}") # 新增调试
                msg_type = message_data.get("type")
                
                if msg_type == "log":
                    print(f"DEBUG: Processing log message: {message_data['message']}") # 新增调试
                    self.log_text_area.config(state=NORMAL)
                    self.log_text_area.insert(END, message_data["message"] + "\n")
                    self.log_text_area.see(END) # 滚动到底部
                    self.log_text_area.config(state=DISABLED)
                    print("DEBUG: Log message processed and displayed.") # 新增调试
                elif msg_type == "news_item":
                    # 在Listbox顶部插入新条目
                    self.news_listbox.insert(0, message_data["text"])
                    # 保持Listbox中最多显示例如100条新闻
                    # if self.news_listbox.size() > 100:
                    #     self.news_listbox.delete(100, END)
                # 可以添加其他消息类型，例如更新状态标签等
        except queue.Empty: # Python 2是 queue.Empty, Python 3是 import queue; queue.Empty
            pass # 队列为空，是正常情况
        except Exception as e:
            print(f"Error processing GUI queue: {e}") # 打印到控制台以防GUI日志出问题

        if self.is_gui_running: # 只有GUI还在运行时才继续调度自身
            self.after(100, self.process_gui_queue) # 100毫秒后再次检查队列

    def on_closing(self):
        """处理窗口关闭事件。"""
        if messagebox.askokcancel("退出", "确定要退出应用程序吗？后台任务将停止。"):
            log_to_gui("应用程序正在关闭...", "APP_LIFECYCLE")
            self.is_gui_running = False # 停止 process_gui_queue 的循环
            
            # 发送信号停止调度器线程
            stop_scheduler_event.set() 
            news_fetch_active.clear()    # 停止新闻获取

            if scheduler_thread and scheduler_thread.is_alive():
                log_to_gui("正在等待调度器线程结束 (最多5秒)...", "APP_LIFECYCLE")
                schedule.clear() # 清除所有挂起的作业，帮助线程更快退出
                scheduler_thread.join(timeout=5) # 等待线程结束，设置超时
                if scheduler_thread.is_alive():
                    log_to_gui("调度器线程未能优雅停止。", "APP_LIFECYCLE_WARN")
            
            self.destroy() # 关闭Tkinter窗口


# FRX新闻获取API
def post_news_to_external_api(news_data, base_url="http://www.chanlunpro.com/"):
    """
    将新闻数据POST到外部API
    参数:
        news_data: 新闻数据字典
        base_url: 目标API的基础URL
    返回:
        bool: 是否成功发送
    """
    try:
        # 构建API端点URL
        api_url = f"{base_url}/api/news"
        
        # 准备POST数据，格式化为外部API期望的格式
        # post_data = {
        #     "title": news_data.get('headline', '')[:500],  # 限制标题长度
        #     "body": news_data.get('body', ''),
        #     "source": news_data.get('source', 'Refinitiv'),
        #     "published_at": news_data.get('published_at', ''),
        #     "category": "FRX新闻",  # 固定分类
        #     "tags": "FRX,外汇,新闻",  # 固定标签
        #     "sentiment_score": 0.0,  # 默认情感分数
        #     "importance_score": 0.8,  # 默认重要性分数
        #     "story_id": news_data.get('story_id', ''),  # 添加story_id用于去重
        #     "language": news_data.get('language', 'en')
        # }
        
        # 发送POST请求
        # print('news_data',news_data)
        session = login_first(base_url)
        news_api_url = f"{base_url}/api/news"
        response = session.post(news_api_url, json=news_data)
      
        
        if response.status_code == 200:
            return True
        else:
            return False
            
    except requests.exceptions.Timeout:
        print('POST超时')
        return False
    except requests.exceptions.ConnectionError:
        print('POST连接失败')
        return False
    except Exception as e:
        return False

# 配置
# BASE_URL = "http://127.0.0.1:9901"
BASE_URL = "http://www.chanlunpro.com/"
LOGIN_URL = f"{BASE_URL}/login"
NEWS_API_URL = f"{BASE_URL}/api/news"

# 测试用户凭据
USERNAME = "admin"
PASSWORD = "admin"

def login_first(base_url="http://www.chanlunpro.com/"):
    """登录获取会话"""
    session = requests.Session()
    login_url = f"{base_url}/login"
    
    # 先获取登录页面（可能需要CSRF token）
    login_page = session.get(login_url)
    if login_page.status_code != 200:
        print(f"❌ 无法访问登录页面: {login_page.status_code}")
        return None
    
    # 登录
    login_data = {
        "username": USERNAME,
        "password": PASSWORD
    }
    
    login_response = session.post(login_url, data=login_data)
    if login_response.status_code == 200:
        print("✅ 登录成功")
        return session
    else:
        print(f"❌ 登录失败: {login_response.status_code}")
        return None

if __name__ == '__main__':
    # 确保全局API Key变量在GUI启动前有初始值（来自.env或默认值）
    # GUI中的StringVar会使用这些初始值
    
    log_to_gui("应用程序启动。", "APP_LIFECYCLE")
    app = NewsAppGUI()
    app.mainloop()
    log_to_gui("应用程序已退出。", "APP_LIFECYCLE")