import datetime
import json
import time
import traceback
import pandas as pd
import os
from flask import request
from chanlun.db import db
from chanlun import fun

# 日志记录器
__log = fun.get_logger()

def receive_economic_data():
    """
    接收经济数据或财务数据的API接口
    接受POST请求，根据data_type字段判断数据类型并调用相应处理逻辑
    支持格式：
    1. 经济数据：{"data_type": "economic_data", "data": [{"indicator_name": "...", "value": "...", ...}]}
    2. 财务数据：{"data_type": "company_financials", "company_code": "...", "company_name": "...", "excel_data": "..."}
    """
    
    try:
        # 检查请求是否为JSON格式
        if not request.is_json:
            return {
                "code": 400,
                "msg": "请求必须是JSON格式",
                "data": None
            }
        
        request_data = request.get_json()
        if not request_data:
            return {
                "code": 400,
                "msg": "请求数据为空",
                "data": None
            }
        
        # 检查数据类型字段
        data_type = request_data.get('data_type', 'economic_data')
        
        if data_type == 'company_financials':
            # 处理财务数据
            return process_company_financials(request_data)
        elif data_type == 'economic_data':
            # 处理经济数据（原有逻辑）
            return process_economic_data_logic(request_data)
        else:
            return {
                "code": 400,
                "msg": f"不支持的数据类型: {data_type}",
                "data": None
            }
            
    except Exception as e:
        __log.error(f"处理请求时发生错误: {str(e)}")
        __log.error(traceback.format_exc())
        return {
            "code": 500,
            "msg": f"服务器内部错误: {str(e)}",
            "data": None
        }

def process_economic_data_logic(request_data):
    """
    处理经济数据的逻辑（从原receive_economic_data函数中提取）
    """
    try:
        # 统一处理为列表格式
        # 支持两种格式：
        # 1. 直接的经济数据：{"indicator_name": "...", ...} 或 [{"indicator_name": "...", ...}]
        # 2. 包装格式：{"source": "...", "data": [{"indicator_name": "...", ...}]}
        data_content = request_data.get('data', request_data)
        if isinstance(data_content, dict):
            economic_data_list = [data_content]
        elif isinstance(data_content, list):
            economic_data_list = data_content
        else:
            return {
                "code": 400,
                "msg": "请求数据格式错误，应为字典或字典列表",
                "data": None
            }
        
        # 保存source信息用于后续处理
        source_info = request_data.get('source', '')
        
        __log.info(f"接收到经济数据请求，共{len(economic_data_list)}条数据")
        
        # 验证必要字段
        required_fields = ['indicator_name', 'latest_value']
        for i, data in enumerate(economic_data_list):
            missing_fields = [field for field in required_fields if field not in data or data[field] is None]
            if missing_fields:
                return {
                    "code": 400,
                    "msg": f"第{i+1}条数据缺少必要字段: {', '.join(missing_fields)}",
                    "data": None
                }
        
        # 处理数据
        processed_data = []
        total_success = 0
        total_db_success = 0
        for i, economic_data in enumerate(economic_data_list):
            try:
                # 处理日期格式
                latest_value = economic_data.get('latest_value')
                latest_value_date_str = economic_data.get('latest_value_date')
                previous_value_date_str = economic_data.get('previous_value_date')
                
                try:
                    if isinstance(latest_value_date_str, str):
                        latest_value_date = datetime.datetime.fromisoformat(latest_value_date_str.replace('Z', '+00:00'))
                    else:
                        latest_value_date = datetime.datetime.now()
                except (ValueError, TypeError):
                    latest_value_date = datetime.datetime.now()
                
                try:
                    if isinstance(previous_value_date_str, str):
                        previous_value_date = datetime.datetime.fromisoformat(previous_value_date_str.replace('Z', '+00:00'))
                    else:
                        previous_value_date = None
                except (ValueError, TypeError):
                    previous_value_date = None
                
                # 安全的数值转换函数
                def safe_float_convert(value, default=None):
                    if value is None:
                        return default
                    if isinstance(value, (int, float)):
                        return float(value)
                    if isinstance(value, str):
                        try:
                            return float(value)
                        except (ValueError, TypeError):
                            return default
                    # 如果是字典类型，尝试提取'value'字段
                    if isinstance(value, dict):
                        if 'value' in value:
                            return safe_float_convert(value['value'], default)
                        # 如果字典中没有'value'字段，返回默认值
                        return default
                    # 如果是其他类型，返回默认值
                    return default
                
                def safe_int_convert(value, default=None):
                    if value is None:
                        return default
                    if isinstance(value, int):
                        return value
                    if isinstance(value, (float, str)):
                        try:
                            return int(float(value))
                        except (ValueError, TypeError):
                            return default
                    # 如果是字典类型，尝试提取'value'字段
                    if isinstance(value, dict):
                        if 'value' in value:
                            return safe_int_convert(value['value'], default)
                        # 如果字典中没有'value'字段，返回默认值
                        return default
                    # 如果是其他类型，返回默认值
                    return default
                    
                # 构建经济数据数据库存储结构
                economic_db_data = {
                    'ds_mnemonic': economic_data.get('ds_mnemonic', f"ECON_{int(time.time() * 1000) + i}"),
                    'indicator_name': economic_data.get('indicator_name'),
                    'latest_value': safe_float_convert(economic_data.get('latest_value'), None),
                    'latest_value_date': latest_value_date,
                    'previous_value': safe_float_convert(economic_data.get('previous_value'), None),
                    'previous_value_date': previous_value_date,
                    'previous_year_value': safe_float_convert(economic_data.get('previous_year_value'), None),
                    'yoy_change_pct': safe_float_convert(economic_data.get('yoy_change_pct'), None),
                    'year': safe_int_convert(economic_data.get('year'), datetime.datetime.now().year),
                    'units': economic_data.get('units', ''),
                    'source': economic_data.get('source', source_info)
                }
                
                # 保存经济数据到数据库
                db_save_success = False
                try:
                    # 使用db.economic_data_insert方法
                    success = db.economic_data_insert(economic_db_data)
                    
                    if success:
                        __log.info(f"第{i+1}条经济数据已保存到数据库: {economic_db_data['indicator_name']}")
                        db_save_success = True
                        total_db_success += 1
                    else:
                        __log.error(f"第{i+1}条经济数据保存到数据库失败")
                        
                except Exception as db_error:
                    __log.error(f"第{i+1}条经济数据保存到数据库失败: {str(db_error)}")
                
                # 构建返回的数据项目结构
                data_item = {
                    'ds_mnemonic': economic_db_data['ds_mnemonic'],
                    'indicator_name': economic_db_data['indicator_name'],
                    'latest_value_date': economic_db_data['latest_value_date'].isoformat() if economic_db_data['latest_value_date'] else None,
                    'latest_value': economic_db_data['latest_value'],
                    'previous_value': economic_db_data['previous_value'],
                    'previous_value_date': economic_db_data['previous_value_date'].isoformat() if economic_db_data['previous_value_date'] else None,
                    'previous_year_value': economic_db_data['previous_year_value'],
                    'yoy_change_pct': economic_db_data['yoy_change_pct'],
                    'year': economic_db_data['year'],
                    'units': economic_db_data['units'],
                    'source': economic_db_data['source'],
                    'created_at': datetime.datetime.now().isoformat(),
                    'db_saved': db_save_success
                }
                
                processed_data.append(data_item)
                if db_save_success:
                    total_success += 1
                
                __log.info(f"第{i+1}条经济数据处理完成: {data_item['indicator_name']}")
                
            except Exception as e:
                __log.error(f"处理第{i+1}条经济数据时发生错误: {str(e)}")
                # 继续处理下一条数据
                continue
        
        return {
            "code": 0,
            "msg": f"批量经济数据接收完成，共处理{len(economic_data_list)}条，成功{total_success}条",
            "data": {
                "received_data": processed_data,
                "processed_at": datetime.datetime.now().isoformat(),
                "summary": {
                    "total_count": len(economic_data_list),
                    "success_count": total_success,
                    "db_success": total_db_success
                }
            }
        }
        
    except Exception as e:
        __log.error(f"处理经济数据时发生错误: {str(e)}")
        __log.error(traceback.format_exc())
        return {
            "code": 500,
            "msg": f"服务器内部错误: {str(e)}",
            "data": None
        }

def process_company_financials(request_data):
    """
    处理公司财务数据的逻辑
    支持Excel文件路径或base64编码的Excel数据
    """
    try:
        company_code = request_data.get('company_code')
        company_name = request_data.get('company_name')
        excel_file_path = request_data.get('excel_file_path')
        excel_base64_data = request_data.get('excel_base64_data')
        print('company_code',company_code)
        print('company_name',company_name)
        print('excel_file_path',excel_file_path)
        # print('excel_base64_data',excel_base64_data)
        if not company_code:
            return {
                "code": 400,
                "msg": "缺少必要字段: company_code",
                "data": None
            }
        
        if not company_name:
            return {
                "code": 400,
                "msg": "缺少必要字段: company_name",
                "data": None
            }
        
        if not excel_file_path and not excel_base64_data:
            return {
                "code": 400,
                "msg": "缺少Excel数据，需要提供excel_file_path或excel_base64_data",
                "data": None
            }
        
        # 处理Excel数据
        total_records = 0
        processed_sheets = []
        
        try:
            if excel_file_path:
                # 使用文件路径处理Excel
                if not os.path.exists(excel_file_path):
                    return {
                        "code": 400,
                        "msg": f"Excel文件不存在: {excel_file_path}",
                        "data": None
                    }
                total_records, processed_sheets = process_excel_file(excel_file_path, company_code, company_name)
            elif excel_base64_data:
                # 处理base64编码的Excel数据
                import base64
                import io
                excel_bytes = base64.b64decode(excel_base64_data)
                total_records, processed_sheets = process_excel_bytes(excel_bytes, company_code, company_name)
                print('total_records',total_records)
                print('processed_sheets',processed_sheets)
            if total_records > 0:
                __log.info(f"公司财务数据已保存到数据库: {company_code}, 共{total_records}条记录")
                return {
                    "code": 0,
                    "msg": f"财务数据接收成功，共处理{total_records}条记录",
                    "data": {
                        "company_code": company_code,
                        "company_name": company_name,
                        "total_records": total_records,
                        "processed_sheets": processed_sheets,
                        "processed_at": datetime.datetime.now().isoformat(),
                        "db_saved": True
                    }
                }
            else:
                return {
                    "code": 400,
                    "msg": "未找到有效的财务数据",
                    "data": None
                }
                
        except Exception as excel_error:
            __log.error(f"Excel数据处理失败: {str(excel_error)}")
            return {
                "code": 500,
                "msg": f"Excel数据处理失败: {str(excel_error)}",
                "data": None
            }
        
    except Exception as e:
        __log.error(f"处理财务数据时发生错误: {str(e)}")
        __log.error(traceback.format_exc())
        return {
            "code": 500,
            "msg": f"服务器内部错误: {str(e)}",
            "data": None
        }

def process_excel_file(excel_file_path, company_code, company_name):
    """
    处理Excel文件，提取财务数据并保存到数据库
    返回: (总记录数, 处理的工作表列表)
    """
    try:
        xls = pd.ExcelFile(excel_file_path)
        total_records = 0
        processed_sheets = []
        
        for sheet_name in xls.sheet_names:
            __log.info(f"Processing sheet: {sheet_name}")
            
            if any(keyword in sheet_name for keyword in ['资产负债表', '利润表', '现金流量表', '损益表']):
                records_count = process_financial_sheet(xls, sheet_name, company_code, company_name)
                if records_count > 0:
                    total_records += records_count
                    processed_sheets.append({
                        'sheet_name': sheet_name,
                        'records_count': records_count
                    })
        
        return total_records, processed_sheets
        
    except Exception as e:
        __log.error(f"处理Excel文件失败: {str(e)}")
        raise e

def process_excel_bytes(excel_bytes, company_code, company_name):
    """
    处理Excel字节数据，提取财务数据并保存到数据库
    返回: (总记录数, 处理的工作表列表)
    """
    try:
        import io
        excel_io = io.BytesIO(excel_bytes)
        xls = pd.ExcelFile(excel_io)
        total_records = 0
        processed_sheets = []
        
        for sheet_name in xls.sheet_names:
            __log.info(f"Processing sheet: {sheet_name}")
            
            if any(keyword in sheet_name for keyword in ['资产负债表', '利润表', '现金流量表', '损益表']):
                records_count = process_financial_sheet(xls, sheet_name, company_code, company_name)
                if records_count > 0:
                    total_records += records_count
                    processed_sheets.append({
                        'sheet_name': sheet_name,
                        'records_count': records_count
                    })
        print('total_records',total_records)
        # print('processed_sheets',processed_sheets)
        return total_records, processed_sheets
        
    except Exception as e:
        __log.error(f"处理Excel字节数据失败: {str(e)}")
        raise e

def process_financial_sheet(xls, sheet_name, company_code, company_name):
    """
    处理单个财务报表工作表
    返回: 处理的记录数
    """
    try:
        # 读取原始数据，不设置index_col
        df_raw = pd.read_excel(xls, sheet_name=sheet_name)
        __log.info(f"Raw DataFrame shape: {df_raw.shape}")
        
        # 找到日期行（通常在第4行，索引为3）
        date_row_idx = None
        for i in range(min(10, len(df_raw))):
            row = df_raw.iloc[i]
            # 检查是否包含年份信息
            if any(str(cell).strip().endswith('年3月') or str(cell).strip().endswith('年6月') or 
                  str(cell).strip().endswith('年9月') or str(cell).strip().endswith('年12月') 
                  for cell in row if pd.notna(cell)):
                date_row_idx = i
                __log.info(f"Found date row at index: {date_row_idx}")
                break
        
        if date_row_idx is None:
            __log.warning(f"Could not find date row in sheet: {sheet_name}")
            return 0
            
        # 提取日期列
        date_row = df_raw.iloc[date_row_idx]
        date_columns = []
        for col_idx, cell in enumerate(date_row):
            if pd.notna(cell) and isinstance(cell, str):
                cell_str = str(cell).strip()
                if ('年' in cell_str and ('月' in cell_str)):
                    date_columns.append((col_idx, cell_str))
        
        __log.info(f"Found date columns: {date_columns}")
        
        # 从日期行之后开始处理数据
        data_start_row = date_row_idx + 1
        total_records = 0
        
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
                __log.warning(f"Skipping invalid date: {date_str}, error: {e}")
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
                        __log.warning(f"Error processing row {row_idx}: {e}")
                        continue

            if financials:
                __log.info(f"Inserting data for {company_name} ({company_code}), Report Date: {report_date}, Statement: {sheet_name}, Items: {len(financials)}")
                success = db.company_financials_insert(
                    code=company_code,
                    name=company_name,
                    statement_type=sheet_name,
                    report_date=report_date,
                    financials=financials
                )
                if success:
                    total_records += len(financials)
                else:
                    __log.error(f"Failed to insert data for {report_date} in {sheet_name}")
            else:
                __log.warning(f"No valid financial data found for {date_str} in {sheet_name}")
        
        return total_records
        
    except Exception as e:
        __log.error(f"处理工作表 {sheet_name} 失败: {str(e)}")
        return 0

def get_economic_data(indicator_name=None, ds_mnemonic=None, year=None, limit=100):
    """
    获取经济数据的API接口
    支持按指标名称、数据源助记符和年份筛选
    """
    try:
        # 使用db.economic_data_query方法
        results = db.economic_data_query(
            indicator_name=indicator_name,
            ds_mnemonic=ds_mnemonic,
            year=year,
            limit=limit
        )
        
        if results:
            data_list = []
            for economic_data in results:
                data_item = {
                    'id': economic_data.id,
                    'ds_mnemonic': economic_data.ds_mnemonic,
                    'indicator_name': economic_data.indicator_name,
                    'latest_value_date': economic_data.latest_value_date.isoformat() if hasattr(economic_data.latest_value_date, 'isoformat') and economic_data.latest_value_date else (economic_data.latest_value_date if economic_data.latest_value_date else None),
                    'latest_value': economic_data.latest_value,
                    'previous_value': economic_data.previous_value,
                    'previous_value_date': economic_data.previous_value_date.isoformat() if hasattr(economic_data.previous_value_date, 'isoformat') and economic_data.previous_value_date else (economic_data.previous_value_date if economic_data.previous_value_date else None),
                    'previous_year_value': economic_data.previous_year_value,
                    'yoy_change_pct': economic_data.yoy_change_pct,
                    'year': economic_data.year,
                    'units': economic_data.units,
                    'source': economic_data.source,
                    'created_at': economic_data.created_at.isoformat() if economic_data.created_at else None,
                    'updated_at': economic_data.updated_at.isoformat() if economic_data.updated_at else None
                }
                data_list.append(data_item)
            
            return {
                "code": 0,
                "msg": f"查询成功，共找到{len(data_list)}条数据",
                "data": {
                    "economic_data": data_list,
                    "query_params": {
                        "indicator_name": indicator_name,
                        "ds_mnemonic": ds_mnemonic,
                        "year": year,
                        "limit": limit
                    },
                    "queried_at": datetime.datetime.now().isoformat()
                }
            }
        else:
            return {
                "code": 0,
                "msg": "未找到匹配的数据",
                "data": {
                    "economic_data": [],
                    "query_params": {
                        "indicator_name": indicator_name,
                        "ds_mnemonic": ds_mnemonic,
                        "year": year,
                        "limit": limit
                    },
                    "queried_at": datetime.datetime.now().isoformat()
                }
            }
            
    except Exception as e:
        __log.error(f"查询经济数据时发生错误: {str(e)}")
        __log.error(traceback.format_exc())
        return {
            "code": 500,
            "msg": f"服务器内部错误: {str(e)}",
            "data": None
        }