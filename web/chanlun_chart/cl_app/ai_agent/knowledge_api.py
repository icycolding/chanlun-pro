#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
知识库管理 API
提供对产品知识库的增删改查接口
"""

from flask import Blueprint, request, jsonify
from flask_login import login_required
from .product_db import get_product_db
import logging

logger = logging.getLogger(__name__)

knowledge_bp = Blueprint('knowledge_api', __name__)

@knowledge_bp.route('/api/knowledge/products', methods=['GET'])
@login_required
def list_products():
    """获取产品列表"""
    try:
        limit = int(request.args.get('limit', 100))
        db = get_product_db()
        products = db.get_all_products(limit=limit)
        return jsonify({"ok": True, "data": products})
    except Exception as e:
        logger.error(f"List products error: {e}")
        return jsonify({"ok": False, "msg": str(e)})

@knowledge_bp.route('/api/knowledge/product/add', methods=['POST'])
@login_required
def add_product():
    """新增产品"""
    try:
        data = request.json
        if not data:
            return jsonify({"ok": False, "msg": "No data provided"})
            
        db = get_product_db()
        success = db.add_product(data)
        
        if success:
            return jsonify({"ok": True, "msg": "Product added successfully"})
        else:
            return jsonify({"ok": False, "msg": "Failed to add product"})
    except Exception as e:
        logger.error(f"Add product error: {e}")
        return jsonify({"ok": False, "msg": str(e)})

@knowledge_bp.route('/api/knowledge/product/update', methods=['POST'])
@login_required
def update_product():
    """更新产品"""
    try:
        data = request.json
        symbol = data.get('symbol')
        if not symbol:
            return jsonify({"ok": False, "msg": "Symbol is required"})
            
        db = get_product_db()
        success = db.update_product(symbol, data)
        
        if success:
            return jsonify({"ok": True, "msg": "Product updated successfully"})
        else:
            return jsonify({"ok": False, "msg": "Failed to update product"})
    except Exception as e:
        logger.error(f"Update product error: {e}")
        return jsonify({"ok": False, "msg": str(e)})

@knowledge_bp.route('/api/knowledge/product/delete', methods=['POST'])
@login_required
def delete_product():
    """删除产品"""
    try:
        data = request.json
        symbol = data.get('symbol')
        if not symbol:
            return jsonify({"ok": False, "msg": "Symbol is required"})
            
        db = get_product_db()
        success = db.delete_product(symbol)
        
        if success:
            return jsonify({"ok": True, "msg": "Product deleted successfully"})
        else:
            return jsonify({"ok": False, "msg": "Failed to delete product"})
    except Exception as e:
        logger.error(f"Delete product error: {e}")
        return jsonify({"ok": False, "msg": str(e)})

@knowledge_bp.route('/api/knowledge/product/init', methods=['POST'])
@login_required
def init_products():
    """从映射文件重新初始化数据"""
    try:
        db = get_product_db()
        db.init_data_from_mapper()
        return jsonify({"ok": True, "msg": "Products initialized from mapper"})
    except Exception as e:
        logger.error(f"Init products error: {e}")
        return jsonify({"ok": False, "msg": str(e)})
