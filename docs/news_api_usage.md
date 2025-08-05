# 新闻API接口使用说明

## 概述

缠论系统新增了新闻数据接收API接口，允许外部系统通过HTTP POST请求向系统发送新闻数据进行处理和分析。

## 接口信息

- **接口地址**: `POST /api/news`
- **完整URL**: `http://127.0.0.1:9900/api/news`
- **认证方式**: 需要登录认证
- **数据格式**: 支持JSON和Form两种格式

## 请求参数

### 必要字段

| 字段名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| title | string | 是 | 新闻标题 |
| body | string | 是 | 新闻正文内容 |
| source | string | 是 | 新闻来源 |
| published_at | string | 是 | 发布时间 (ISO格式) |

### 可选字段

| 字段名 | 类型 | 必填 | 默认值 | 说明 |
|--------|------|------|--------|------|
| id | integer | 否 | 时间戳 | 新闻ID |
| story_id | string | 否 | '' | 故事ID |
| language | string | 否 | 'zh' | 语言代码 |

## 请求示例

### JSON格式请求

```bash
curl -X POST http://127.0.0.1:9900/api/news \
  -H "Content-Type: application/json" \
  -d '{
    "id": 12345,
    "story_id": "story_001",
    "title": "市场重要新闻：央行宣布降准政策",
    "body": "中国人民银行今日宣布，为支持实体经济发展，决定于近期实施降准措施，释放长期资金约1万亿元。",
    "source": "财经新闻网",
    "published_at": "2024-01-15T10:30:00",
    "language": "zh"
  }'
```

### Python请求示例

```python
import requests
import json
from datetime import datetime

# 新闻数据
news_data = {
    'id': 12345,
    'story_id': 'story_001',
    'title': '市场重要新闻：央行宣布降准政策',
    'body': '中国人民银行今日宣布，为支持实体经济发展，决定于近期实施降准措施。',
    'source': '财经新闻网',
    'published_at': datetime.now().isoformat(),
    'language': 'zh'
}

# 发送请求
response = requests.post(
    'http://127.0.0.1:9900/api/news',
    json=news_data,
    headers={'Content-Type': 'application/json'}
)

# 处理响应
if response.status_code == 200:
    result = response.json()
    print(f"响应: {json.dumps(result, ensure_ascii=False, indent=2)}")
else:
    print(f"请求失败: {response.status_code}")
```

### Form格式请求

```bash
curl -X POST http://127.0.0.1:9900/api/news \
  -F "title=市场重要新闻：央行宣布降准政策" \
  -F "body=中国人民银行今日宣布，为支持实体经济发展，决定于近期实施降准措施。" \
  -F "source=财经新闻网" \
  -F "published_at=2024-01-15T10:30:00" \
  -F "language=zh"
```

## 响应格式

### 成功响应

```json
{
  "code": 0,
  "msg": "新闻数据接收成功",
  "data": {
    "received_news": {
      "id": 12345,
      "story_id": "story_001",
      "title": "市场重要新闻：央行宣布降准政策",
      "body": "中国人民银行今日宣布，为支持实体经济发展，决定于近期实施降准措施。",
      "source": "财经新闻网",
      "published_at": "2024-01-15T10:30:00",
      "language": "zh",
      "created_at": "2024-01-15T10:35:00.123456"
    },
    "processed_at": "2024-01-15T10:35:00.123456"
  }
}
```

### 错误响应

#### 缺少必要字段

```json
{
  "code": 400,
  "msg": "缺少必要字段: body",
  "data": null
}
```

#### 服务器错误

```json
{
  "code": 500,
  "msg": "处理新闻数据时发生错误: 具体错误信息",
  "data": null
}
```

## 状态码说明

| HTTP状态码 | 业务状态码 | 说明 |
|------------|------------|------|
| 200 | 0 | 成功 |
| 200 | 400 | 请求参数错误 |
| 200 | 500 | 服务器内部错误 |
| 401 | - | 未认证 |
| 403 | - | 无权限 |

## 测试工具

项目提供了测试脚本 `test_news_api.py`，可以用来测试接口功能：

```bash
# 运行测试脚本
python test_news_api.py
```

测试脚本会执行以下测试：
1. 正常新闻数据提交测试
2. 缺少必要字段的错误处理测试
3. Form数据格式提交测试

## 使用流程

1. **启动服务**
   ```bash
   python web/chanlun_chart/app.py
   ```

2. **登录系统**
   - 访问 `http://127.0.0.1:9900`
   - 使用配置的密码登录（如未设置密码则自动登录）

3. **发送新闻数据**
   - 使用POST请求发送新闻数据到 `/api/news`
   - 确保包含所有必要字段

4. **处理响应**
   - 检查响应中的 `code` 字段
   - `code=0` 表示成功，其他值表示错误

## 扩展功能

当前接口主要用于接收新闻数据，后续可以扩展以下功能：

1. **数据存储**: 将新闻数据保存到数据库
2. **AI分析**: 集成AI增强分析功能，对新闻进行情感分析
3. **市场关联**: 将新闻与相关股票、市场进行关联
4. **实时推送**: 将重要新闻实时推送给用户
5. **批量处理**: 支持批量新闻数据提交

## 注意事项

1. **认证要求**: 接口需要登录认证，请确保已登录系统
2. **数据格式**: 支持JSON和Form两种格式，推荐使用JSON
3. **字段验证**: 必要字段缺失会返回400错误
4. **时间格式**: `published_at` 字段建议使用ISO格式
5. **编码格式**: 支持UTF-8编码，可以处理中文内容
6. **日志记录**: 所有新闻数据接收都会记录到系统日志

## 故障排除

### 常见问题

1. **连接失败**
   - 检查服务是否启动
   - 确认端口9900是否可访问

2. **认证失败**
   - 确保已登录系统
   - 检查session是否有效

3. **参数错误**
   - 检查必要字段是否完整
   - 确认数据格式是否正确

4. **服务器错误**
   - 查看系统日志获取详细错误信息
   - 检查服务器资源是否充足

### 调试建议

1. 使用测试脚本验证接口功能
2. 查看系统日志了解处理过程
3. 使用curl或Postman等工具进行接口测试
4. 检查网络连接和防火墙设置