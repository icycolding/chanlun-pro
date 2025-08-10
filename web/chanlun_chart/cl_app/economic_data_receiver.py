import datetime
import json
import time
import traceback
from flask import request
from chanlun.db import db
from chanlun import fun

# 日志记录器
__log = fun.get_logger()

def receive_economic_data():
    """
    接收经济数据的API接口
    接受POST请求，处理单条或多条经济数据，并存储到数据库
    支持格式：
    1. 单条数据：{"indicator_name": "...", "value": "...", ...}
    2. 多条数据：[{"indicator_name": "...", "value": "..."}, {...}]
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
        
        # 统一处理为列表格式
        # 支持两种格式：
        # 1. 直接的经济数据：{"indicator_name": "...", ...} 或 [{"indicator_name": "...", ...}]
        # 2. 包装格式：{"source": "...", "data": [{"indicator_name": "...", ...}]}
        if isinstance(request_data, dict):
            # 检查是否是包装格式
            if 'data' in request_data and isinstance(request_data['data'], (list, dict)):
                # 包装格式，提取data字段
                data_content = request_data['data']
                if isinstance(data_content, dict):
                    economic_data_list = [data_content]
                else:
                    economic_data_list = data_content
                # 保存source信息用于后续处理
                source_info = request_data.get('source', '')
            else:
                # 直接格式
                economic_data_list = [request_data]
                source_info = ''
        elif isinstance(request_data, list):
            economic_data_list = request_data
            source_info = ''
        else:
            return {
                "code": 400,
                "msg": "请求数据格式错误，应为字典或字典列表",
                "data": None
            }
        
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
                    # 使用db.economic_data_insert方法，参考receive_news()的处理方式
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

def get_economic_data(indicator_name=None, ds_mnemonic=None, year=None, limit=100):
    """
    获取经济数据的API接口
    支持按指标名称、数据源助记符和年份筛选
    """
    try:
        # 使用db.economic_data_query方法，参考receive_news()的处理方式
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
                        "country_code": country_code,
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