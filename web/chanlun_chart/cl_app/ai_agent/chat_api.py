#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AGI Chat API
提供流式对话接口
"""

from flask import Blueprint, request, Response, stream_with_context, jsonify
from flask_login import login_required
from .agent import AGIAgent
import json
import logging

logger = logging.getLogger(__name__)

chat_bp = Blueprint('chat_api', __name__)

# 全局 Agent 实例 (避免每次请求都初始化)
_agent = None

def get_agent():
    global _agent
    if _agent is None:
        _agent = AGIAgent()
    return _agent

@chat_bp.route('/api/ai/chat', methods=['POST'])
@login_required
def chat():
    """
    流式对话接口
    Input: { "messages": [...] }
    Output: SSE Stream
    """
    try:
        data = request.json
        messages = data.get('messages', [])
        
        if not messages:
            return jsonify({"error": "No messages provided"}), 400

        def generate():
            agent = get_agent()
            for chunk_str in agent.chat_stream(messages):
                yield f"data: {chunk_str}\n\n"
            yield "data: [DONE]\n\n"

        return Response(stream_with_context(generate()), mimetype='text/event-stream')

    except Exception as e:
        logger.error(f"Chat API error: {e}")
        return jsonify({"error": str(e)}), 500
