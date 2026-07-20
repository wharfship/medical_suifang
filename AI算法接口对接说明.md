# AI 算法接口对接说明

## 1. 适用范围

本文件说明医疗随访系统第一版 HTTP API，供微信小程序、Web 管理端或 App 对接。

AI 算法继续由 Python 服务端调用阿里云百炼 DashScope；客户端不直接调用模型，也不会获得 `DASHSCOPE_API_KEY`。

接口文档页面在服务启动后可访问：

```text
https://<你的域名>/api/docs
```

## 2. 第一版范围

已实现以下 5 个接口：

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/api/v1/health` | 检查 API 服务是否存活 |
| `POST` | `/api/v1/followups` | 创建一次随访并返回第一问 |
| `GET` | `/api/v1/followups/{followup_id}` | 恢复该次随访的当前状态 |
| `POST` | `/api/v1/followups/{followup_id}/messages` | 提交本轮文字回答并返回下一问 |
| `POST` | `/api/v1/followups/{followup_id}/reports` | 上传化验单并返回 OCR 结果与下一问 |

第一版不包含微信登录、权限控制、人工修改结果、Excel 下载接口、OCR 结果下载或数据库长期存储。完成的随访会自动将最终 Excel 保存到服务器 `outputs` 目录。

## 3. 随访状态约定

创建随访后，服务端返回 `followup_id`。小程序必须保存该值，并在后续回答、上传和恢复页面时使用它。

服务端保存字段模板、字段依赖、对话历史、追问次数和模型密钥。小程序只提交本轮回答或文件，不传整段历史、不传 `metadata`，也不传当前字段名。

第一版会话保存在 API 进程内存中：**API 服务重启后，未完成的随访会失效。**

当全部字段完成时，服务端会自动保存最终 Excel，无需小程序额外调用接口：

```text
outputs/
  张三_20260001/
    2026／07／20／14：30随访/
      medical_data.xlsx
    汇总结果.xlsx
```

当前只保存最终 `medical_data.xlsx` 和患者汇总表；化验单原文件与 OCR 中间结果不会归档。小程序不会收到服务器文件路径，也不提供下载接口。

## 4. 接口定义

### 4.1 服务健康检查

`GET /api/v1/health`

响应：

```json
{
  "status": "ok"
}
```

### 4.2 创建随访

`POST /api/v1/followups`

请求体：

```json
{
  "patient_name": "张三",
  "student_id": "20260001"
}
```

字段要求：

- `patient_name`：2 至 20 个中文、英文字母、空格或中点字符，必填。
- `student_id`：8 位数字，必填。
- 随访日期由服务端自动使用当天日期，客户端不传此字段。

成功响应示例：

```json
{
  "followup_id": "a0b1c2d3-...",
  "status": "in_progress",
  "patient_name": "张三",
  "student_id": "20260001",
  "progress": {
    "completed": 0,
    "total": 20,
    "inactive": 0,
    "percent": 0
  },
  "current_field": {
    "label": "当前有无高血压"
  },
  "question": "您目前有高血压吗？",
  "messages": [
    {
      "role": "assistant",
      "content": "您好，我是医疗随访助手，需要了解您的健康状况。"
    }
  ],
  "upload_available": false,
  "accepted_report_types": [".docx", ".jpeg", ".jpg", ".png"]
}
```

`messages` 中的 `role` 只有 `assistant` 或 `user`，小程序可直接用于恢复聊天记录。

### 4.3 获取随访状态

`GET /api/v1/followups/{followup_id}`

返回结构与创建随访接口相同。小程序重新打开页面或切回前台后，调用该接口恢复聊天记录、进度和当前问题。

### 4.4 提交患者回答

`POST /api/v1/followups/{followup_id}/messages`

请求体：

```json
{
  "content": "没有。"
}
```

响应在随访状态基础上增加 `parsed_result`：

```json
{
  "parsed_result": {
    "status": "done",
    "completion": "complete",
    "field_value": "否",
    "confidence": 0.96,
    "reasoning": "患者明确否认高血压。",
    "evidence": "patient: 没有"
  },
  "question": "您最近有去医院进行检查吗？",
  "status": "in_progress"
}
```

`parsed_result.status` 可能为：`done`、`ask_again`、`later`、`manual_review`。服务端会继续执行既有字段规则和追问上限；达到追问上限后会自动结束当前字段。

当 `status` 为 `finished`、`current_field` 和 `question` 均为 `null` 时，代表本次随访已完成，服务端已自动写入最终 Excel 并刷新患者汇总表。

### 4.5 上传化验单

`POST /api/v1/followups/{followup_id}/reports`

请求格式：`multipart/form-data`

| 表单字段 | 类型 | 说明 |
|---|---|---|
| `file` | 文件 | 必填；`.docx`、`.png`、`.jpg` 或 `.jpeg`，最大 20MB |

用户在小程序选择并确认上传化验单后调用此接口。服务端根据当前随访字段处理文件：

- 化验单字段：调用 OCR，返回 `rows`，并尝试自动提取当前字段值。
- `肾脏彩超`字段：记录“已上传肾脏彩超”，第一版不保存文件供下载。

成功响应示例：

```json
{
  "rows": [
    {
      "item_name": "肌酐",
      "abbr": "CREA",
      "result": "85",
      "unit": "umol/L",
      "reference_range": "57-111"
    }
  ],
  "parsed_result": {
    "status": "done",
    "completion": "complete",
    "field_value": "85",
    "confidence": 1.0
  },
  "question": "下一题问题文本",
  "status": "in_progress"
}
```

上传文件仅用于本次识别，识别完成后会删除临时文件，不会归档到 `outputs`；响应中不会提供服务器文件路径。

## 5. 错误响应

错误响应格式由 FastAPI 提供，关键 HTTP 状态如下：

| HTTP 状态 | 场景 |
|---|---|
| `400` | 姓名、学工号、回答内容或上传文件不合法；随访已经结束 |
| `404` | `followup_id` 不存在，或 API 重启后内存会话失效 |
| `422` | 请求 JSON 或表单字段缺失、类型错误 |
| `502` | DashScope 调用或化验单识别失败，可提示用户稍后重试 |
| `500` | 随访已完成但服务器写入最终 Excel 失败，可重试获取随访状态触发再次保存 |

## 6. 部署说明

新增服务入口为 `api.py`，systemd 模板为：

```text
deploy/medical-algorithm-api.service
```

它使用同一份服务器环境变量文件 `/etc/medical_suifang.env`，并在 `127.0.0.1:8000` 监听。现有 Gradio 服务继续在 `7860` 端口运行。Nginx 配置已增加 `/api/` 反向代理。

部署前必须：

1. 在服务器虚拟环境中安装更新后的 `requirements.txt`。
2. 仅在 `/etc/medical_suifang.env` 中配置新的 `DASHSCOPE_API_KEY`。
3. 使用 HTTPS 域名对外提供 API，随后在微信小程序后台配置该业务域名。
4. 在正式对外开放前补充微信登录和权限控制。

## 7. 安全说明

当前第一版没有鉴权，**只能用于受控测试环境，不得直接公开暴露到互联网。**

DashScope 密钥、真实患者资料、服务器登录凭据和生产环境变量文件不得提交 Git 仓库或提供给小程序客户端。
