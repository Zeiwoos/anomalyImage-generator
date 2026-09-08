# 工业异常生成与审核 Pipeline v2

版本：20260811

这是一个可迁移的“视觉 LLM 生成代理 + 图像生成 CORE + 人工审核”项目。程序读取带 LabelMe 标注的待处理图像，结合知识库与异常参考库规划编辑区域、选择参考、生成候选、执行自动质检，并在网页中完成人工质量审核、局部 ROI 重生成和 Mask 修订。

本发布包已经脱敏：不包含原机器的 API Key、API 地址、数据集路径、数据库、审核结果、生成中间图或 Python/Conda 固定路径。

## 五分钟快速启动（首次使用必读）

首次拿到干净发布包时，必须按以下顺序执行。**`start_review_tool.bat` 不会自动扫描数据集；如果漏掉第 4 步，网页会提示“当前筛选下没有可显示样本”。**

1. 在项目根目录打开 CMD，创建运行环境：

   ```bat
   setup_env.bat
   ```

2. 编辑 `config.json`，把 `dataset.root` 设置为待处理 LabelMe 数据集根目录。

3. 检查 Python、知识库、参考库和配置：

   ```bat
   start_review_tool.bat --check
   ```

4. **扫描数据集并建立审核数据库：**

   ```bat
   run_pipeline.bat scan
   ```

   扫描命令应输出发现的样本数量。首次使用、切换 `dataset.root`，或者希望重新读取新增/修改后的 LabelMe 标注时，都需要再次执行该命令。

5. 启动审核台：

   ```bat
   start_review_tool.bat
   ```

6. 浏览器打开后，在右上角“API 配置”中填写自己的 Base URL 和 API Key，先执行连接测试，再开始生成。

首次运行的最短命令顺序为：

```bat
setup_env.bat
start_review_tool.bat --check
run_pipeline.bat scan
start_review_tool.bat
```

## 包含内容

- `anomaly_factory/`：Pipeline、视觉代理、CORE 适配器、审核服务和网页前端。
- `knowledge-bank/`：标签映射、各类异常规律、反例规则、Prompt 协议和质检规则。
- `Anomaly-reference/`：允许随项目分发的异常/正常参考库及 LabelMe 标注。
- `tests/`：离线单元测试。
- `config.json`：当前运行配置；所有项目内目录默认使用相对路径。
- `V2完整生成流程分析.md`：视觉 LLM、参考图、CORE、Mask、多 ROI、重试和导出的完整实现说明。
- `性能优化说明.md`：当前快速平衡模式与并行规划说明。
- `中间产物/`：运行后自动产生，不随发布包分发。

## 1. 环境准备

推荐 Python 3.10 或更高版本。

最省事的方式是双击：

```bat
setup_env.bat
```

它会在项目内创建 `.venv`，安装 `requirements.txt`，并写入只在本机使用、已被 `.gitignore` 忽略的 `python_path.local.txt`。

也可以先激活已有 Conda 环境，再直接运行启动脚本。Python 查找顺序为：

1. 环境变量 `PIPELINE_PYTHON` 指向的 `python.exe`；
2. `python_path.local.txt` 中的路径；
3. 当前激活的 Conda 环境；
4. 项目内 `.venv`；
5. 系统 `PATH` 中的 `python`。

## 2. 配置待处理数据集

编辑 `config.json`：

```json
{
  "dataset": {
    "root": "E:/datasets/my_labelme_dataset"
  }
}
```

Windows 路径建议使用正斜杠 `/`，或把反斜杠写成 `\\`。数据集根目录可以放在任意磁盘；发布包本身不包含业务数据集。

程序会按 `**/*.json` 扫描 LabelMe 标注，并根据 JSON 中的标签、形状和对应原图构建样本与 ROI。一个样本可包含多个标记框；生成模式默认在同一张图上顺序叠加已经成功的 ROI 异常。

## 3. 配置 API（不要把密钥写进 config.json）

推荐方式：启动审核工具后打开右上角“API 配置”，填写 API Base URL 和 API Key。程序只把凭据保存在项目根目录的 `api_credentials.local.json`，该文件已被 `.gitignore` 排除，不能随包复制或提交。

也可以在启动前设置环境变量：

```bat
set "PIPELINE_API_BASE_URL=https://your-api-gateway.example.com"
set "PIPELINE_API_KEY=your-private-key"
start_review_tool.bat
```

`config.json` 默认使用：

- 生图：`POST /v1/images/edits`，模型 `gpt-image-2`，默认质量 `low`（快速平衡模式，可在网页调整为 `high`）；
- 视觉代理：`POST /v1/responses`，模型 `gpt-5.6-sol`；
- 认证：`Authorization: Bearer <PIPELINE_API_KEY>`。

如果网关的协议、模型名或认证方式不同，请按 [CORE_INTEGRATION.md](CORE_INTEGRATION.md) 修改 `config.json`。

## 4. 首次检查、扫描与启动

先运行：

```bat
start_review_tool.bat --check
```

然后执行首次必需的数据集扫描：

```bat
run_pipeline.bat scan
```

扫描成功并输出样本数量后，再启动审核台：

```bat
start_review_tool.bat
```

默认打开 `http://127.0.0.1:8898/`。如果端口被占用，修改 `config.json` 中的 `review.port`。

当前默认每个 ROI 一轮只生成一个候选，并执行一次视觉规划和一次语义质检；质量失败自动反馈重试一次，仍失败则进入人工审核。开启 `intelligence.parallel_planning` 后，下一张图片的视觉规划可与当前 CORE 生成重叠执行，但不会同时启动两个 CORE 生图任务。

进入网页后的推荐流程：

1. 检查 API 配置并执行连接测试；
2. 确认命令行 `run_pipeline.bat scan` 已完成，左侧队列能够看到样本；
3. 在样本页确认标签、ROI、Mask 和“下一次送入生成的 ROI”；
4. 处理待生成队列；
5. 审核候选，按 ROI 通过、驳回并填写精确意见；
6. 对驳回 ROI 加入重生成队列；
7. 全部通过后修改 Mask，并导出最终数据集。

## 5. 命令行操作

```bat
run_pipeline.bat doctor
run_pipeline.bat index-references
run_pipeline.bat scan
run_pipeline.bat generate
run_pipeline.bat generate --queued-only
run_pipeline.bat review
run_pipeline.bat export-approved --output "E:\exports\final_dataset"
```

API 速度测试：

```bat
start_api_speed_test.bat
```

默认地址为 `http://127.0.0.1:8897/`。

