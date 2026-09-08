# CORE 接入说明

外层程序不会把标签判断、提示词路由或审核意见理解交给 CORE。CORE 只负责完成一次受控图像编辑。

当前 `config.json` 默认使用 `openai_image_edits`。同一网关中：GPT-5.6 文本接口可用于外层推理，而真正的像素编辑由 `gpt-image-2` 完成。

## 默认方式：GPT Image 2 Image Edits

程序把源图、alpha mask、知识库参考图和提示词组装为 `multipart/form-data`，调用 `/v1/images/edits`，模型为 `gpt-image-2`。源图和 mask 都在内存中转成同尺寸 PNG；本项目白色 ROI 表示允许编辑，发送前会转换成 Image Edits 所需的透明编辑区域。密钥只在运行时读取，不写入项目。

当源图尺寸满足 GPT Image 2 约束时，程序显式发送原尺寸，例如 `2448x2048`。若网关仍返回同宽高比的较小图片，外层程序只把生成图归一化回源尺寸后再按 ROI 与原图合成；ROI 外始终使用原图像素。宽高比误差超过配置阈值时仍判定 `SIZE_MISMATCH`，不会强行拉伸。

默认适配器不依赖 `/v1/files`。保留的 `openai_responses_image` 只用于明确支持 Files 与 Responses 图像生成协议的兼容网关，不是默认值。

网络配置默认：

```json
{
  "proxy_mode": "direct"
}
```

`direct` 只对本项目 API 请求禁用代理，不修改系统代理设置。如果客户网关必须通过代理访问，可在网页 API 配置或 `config.json` 中切换代理模式。

高分辨率 `quality=high` 可能明显增加耗时。交付包默认使用 `quality=low` 的快速平衡模式，客户可在审核台右上角“API与智能策略”中切换为 `high` 并测试；超时时间也可按网关性能调整。

## 备选一：外部命令包装器（command）

适用于 image2、Nano Banana、私有 SDK 或任何已有 Python 调用代码。配置示例：

```json
{
  "core": {
    "adapter": "command",
    "claude_settings": "",
    "base_url_env": "PIPELINE_API_BASE_URL",
    "api_key_env": "PIPELINE_API_KEY",
    "command": [
      "D:/path/to/python.exe",
      "D:/path/to/core_wrapper.py",
      "--input", "{input}",
      "--mask", "{mask}",
      "--prompt", "{prompt}",
      "--output", "{output}",
      "--references", "{references}"
    ]
  }
}
```

占位符：`{input}`、`{mask}`、`{prompt}`、`{output}`、`{references}`、`{sample_id}`、`{attempt}`。程序使用 `subprocess` 参数数组且 `shell=False`。

密钥不会出现在命令参数。包装器从环境变量读取：

- `CORE_BASE_URL`
- `CORE_API_KEY`

这些值运行时从项目本机凭据文件或系统环境变量读取，不会写入 Prompt、任务清单或审核日志。

包装器必须把一张可解码的完整图片写入 `{output}`。图片宽高应与 `{input}` 完全相同。

## 备选二：通用 JSON/base64 HTTP（http_json）

若图像服务接受 JSON，可设置：

```json
{
  "core": {
    "adapter": "http_json",
    "endpoint": "/v1/images/edits",
    "model": "实际图像编辑模型名",
    "auth_header": "Authorization",
    "auth_scheme": "Bearer",
    "response_base64_field": "data.0.b64_json",
    "response_url_field": "data.0.url"
  }
}
```

请求体包含 `model`、`prompt`、`image`、`mask`、`reference_images`。响应可返回 base64 或图片 URL，字段路径可配置。

`http_json` 是本项目自定义的简化 JSON 协议，不等同于 OpenAI 官方 `/v1/images/edits`（后者使用 multipart/form-data），也不等同于 Responses API。只有服务端明确接受这里列出的 JSON 字段时才使用。
