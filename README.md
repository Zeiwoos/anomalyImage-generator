# 工业异常生成与审核 Pipeline v2

版本：20260811（macOS 适配版）

这是一个可迁移的“视觉 LLM 生成代理 + 图像生成 CORE + 人工审核”项目。程序读取带 LabelMe 标注的待处理图像，结合知识库与异常参考库规划编辑区域、选择参考、生成候选、执行自动质检，并通过网页完成人工审核、局部 ROI 重生成和 Mask 修订。

Windows 仍是本 README 的主要使用平台；当前版本同时提供 macOS/Linux 的 `.sh` 脚本和对应说明。除特别标注的平台差异外，两套入口使用同一份 `config.json`、知识库、数据库和审核网页。

本发布包已经脱敏，不包含 API Key、API 地址、业务数据集、数据库、审核结果、生成中间图或 Python/Conda 固定路径。当前仓库也不包含原发布说明中提到的 `Anomaly-reference/` 参考图库和旧文档 `CORE_INTEGRATION.md`。如需参考图选择能力，必须另行取得 `Anomaly-reference/` 并放到项目根目录，或者在 `config.json` 中配置参考库的实际路径；接口配置则应以所用 API 网关的文档为准。

## 五分钟快速启动（首次使用必读）

首次拿到干净发布包时，必须依次完成环境安装、数据集配置、环境检查、数据集扫描和审核台启动。`start_review_tool.bat` 与 `start_review_tool.sh` 都不会自动扫描数据集；如果漏掉扫描步骤，网页会提示“当前筛选下没有可显示样本”。

### Windows（主要说明）

在项目根目录打开 CMD，执行：

```bat
setup_env.bat
```

随后编辑 `config.json`，把 `dataset.root` 设置为待处理 LabelMe 数据集的绝对路径，例如：

```json
{
  "dataset": {
    "root": "E:/datasets/my_labelme_dataset"
  }
}
```

完成配置后依次执行：

```bat
start_review_tool.bat --check
run_pipeline.bat scan
start_review_tool.bat
```

扫描命令应输出发现的样本数量。首次使用、切换 `dataset.root`，或者需要重新读取新增或修改后的 LabelMe 标注时，都要再次执行 `run_pipeline.bat scan`。

浏览器打开后，在右上角“API 配置”中填写自己的 Base URL 和 API Key，先执行连接测试，再开始生成。审核台默认地址为 `http://127.0.0.1:8898/`。

Windows 首次运行的最短命令顺序为：

```bat
setup_env.bat
start_review_tool.bat --check
run_pipeline.bat scan
start_review_tool.bat
```

### macOS

需要 Python 3.10 或更高版本。首次运行时，在“终端”中进入项目根目录并执行：

```bash
chmod +x ./*.sh TEST/manual_tests/run_tests.sh
./setup_env.sh
```

安装脚本会创建或复用项目内的 `.venv`，安装 `requirements.txt`，并写入仅供本机使用、已被 `.gitignore` 忽略的 `python_path.local.txt`。脚本支持 Intel 与 Apple 芯片，不要求 Conda。若系统没有合适的 Python，可先使用 Homebrew 安装：

```bash
brew install python@3.12
./setup_env.sh
```

随后编辑 `config.json`，把 `dataset.root` 设置为待处理 LabelMe 数据集的绝对路径，例如：

```json
{
  "dataset": {
    "root": "/Users/yourname/datasets/my_labelme_dataset"
  }
}
```

JSON 中不要使用 `~` 代替主目录。路径可以包含中文和空格；在命令行中手动传递此类路径时需要使用双引号。

完成配置后依次执行：

```bash
./start_review_tool.sh --check
./run_pipeline.sh scan
./start_review_tool.sh
```

审核台默认打开 `http://127.0.0.1:8898/`。首次使用、切换 `dataset.root`，或者需要重新读取新增或修改后的 LabelMe 标注时，都要再次执行 `./run_pipeline.sh scan`。

如果不希望自动打开默认浏览器，可以运行：

```bash
./start_review_tool.sh --no-browser
```

## 包含内容与发布边界

- `anomaly_factory/`：Pipeline、视觉代理、CORE 适配器、审核服务和网页前端。
- `knowledge-bank/`：标签映射、各类异常规律、反例规则、Prompt 协议和质检规则。
- `TEST/ai_tests/`：不调用真实 API 的离线自动化测试。
- `TEST/manual_tests/`：面向运行中审核服务的人工接口测试及说明。
- `config.json`：当前运行配置；项目内目录默认使用相对路径，业务数据集可使用绝对路径。
- `V2完整生成流程分析.md`：视觉 LLM、参考图、CORE、Mask、多 ROI、重试和导出的实现说明（以实际发布包中存在的文件为准）。
- `性能优化说明.md`：当前快速平衡模式与并行规划说明（以实际发布包中存在的文件为准）。
- `中间产物/`：运行后自动产生，不随发布包分发。

当前发布包不包含以下内容：

- `Anomaly-reference/`：异常/正常参考图库及其 LabelMe 标注，需要另行取得。
- `CORE_INTEGRATION.md`：旧版 README 曾引用的接口说明，本发布包中不存在。
- API 凭据、API 地址、业务数据集、SQLite 数据库、审核结果和生成中间产物。

## 1. 环境准备与 Python 查找顺序

推荐使用 Python 3.10 或更高版本。Windows 和 macOS 都可以使用项目内 `.venv`，也可以复用已经激活的 Conda 或其他虚拟环境。

### Windows

最简方式是双击 `setup_env.bat`；也可以在项目根目录的 CMD 中运行：

```bat
setup_env.bat
```

该脚本会创建或复用 `.venv`，安装 `requirements.txt`，并写入仅供本机使用的 `python_path.local.txt`。

Windows 启动脚本按以下顺序查找 Python：

1. 环境变量 `PIPELINE_PYTHON` 指向的 `python.exe`；
2. `python_path.local.txt` 中记录的解释器路径；
3. 当前激活的 Conda 环境；
4. 项目内 `.venv\Scripts\python.exe`；
5. 系统 `PATH` 中的 `python`。

### macOS

在项目根目录运行：

```bash
./setup_env.sh
```

macOS/Linux 启动脚本按以下顺序查找 Python：

1. 环境变量 `PIPELINE_PYTHON` 指向的解释器；
2. `python_path.local.txt` 中记录的解释器路径；
3. 当前激活的虚拟环境；
4. 当前激活的 Conda 环境；
5. 项目内 `.venv/bin/python`；
6. 系统 `PATH` 中的 `python3`，最后是 `python`。

无论使用哪种平台，最终选中的解释器都必须是 Python 3.10 或更高版本。

## 2. 配置待处理数据集

编辑 `config.json` 中的 `dataset.root`。Windows 示例：

```json
{
  "dataset": {
    "root": "E:/datasets/my_labelme_dataset"
  }
}
```

macOS 示例：

```json
{
  "dataset": {
    "root": "/Users/yourname/datasets/my_labelme_dataset"
  }
}
```

Windows 路径建议使用正斜杠 `/`，或把反斜杠写成 `\\`。macOS 配置中必须写完整绝对路径，不要用 `~` 代替主目录。数据集根目录可以位于任意磁盘或挂载卷；发布包本身不包含业务数据集。

程序按 `dataset.labelme_glob`（默认 `**/*.json`）递归扫描 LabelMe 标注，再根据 JSON 中的标签、形状和 `imagePath` 查找原图。一个样本可以包含多个标记区域；默认模式会在同一张图上依次叠加已经成功生成的 ROI 异常。

## 3. 配置 API（不要把密钥写进 config.json）

推荐启动审核台后，在右上角“API 配置”中填写 Base URL 和 API Key，并先执行连接测试。程序只会把凭据保存在项目根目录的 `api_credentials.local.json`；该文件已加入 `.gitignore`，不要随发布包复制或手动提交。

Windows 也可以在当前 CMD 中临时设置环境变量：

```bat
set "PIPELINE_API_BASE_URL=https://your-api-gateway.example.com"
set "PIPELINE_API_KEY=your-private-key"
start_review_tool.bat
```

macOS 可以在当前终端中临时设置环境变量：

```bash
export PIPELINE_API_BASE_URL="https://your-api-gateway.example.com"
export PIPELINE_API_KEY="your-private-key"
./start_review_tool.sh
```

关闭对应的 CMD 或终端后，以上临时环境变量会失效。如需长期配置，可以写入个人 shell 配置或使用网页中的 API 配置功能，但不要把密钥写入 `config.json`。

`config.json` 默认使用：

- 生图接口：`POST /v1/images/edits`，模型 `gpt-image-2`，默认质量 `low`；可在网页调整为 `high`。
- 视觉代理接口：`POST /v1/responses`，模型 `gpt-5.6-sol`。
- 认证形式：`Authorization: Bearer <PIPELINE_API_KEY>`。

如果网关的协议、模型名或认证方式不同，需要相应调整 `config.json`。当前发布包不包含旧文档引用的 `CORE_INTEGRATION.md`，因此应以所用网关自身的接口文档为准。

## 4. 数据集、知识库与参考库

知识库位于 `knowledge-bank/`。运行期间产生的 SQLite 数据库、候选图和审核结果默认位于 `中间产物/workspace/`，并已加入 `.gitignore`。

`project.reference_root` 默认指向项目根目录中的 `Anomaly-reference/`。当前发布包没有该目录，因此 `doctor` 会显示 `reference_root.exists` 为 `false`。这不会影响环境安装、LabelMe 扫描和人工审核界面的启动，但会使参考图索引和依赖真实参考图的生成策略不可用。

取得参考库后，将其放到项目根目录，或者在 `config.json` 中把 `project.reference_root` 改为实际路径，然后建立索引。

Windows：

```bat
run_pipeline.bat index-references
```

macOS：

```bash
./run_pipeline.sh index-references
```

## 5. 首次检查、扫描与启动

Windows：

```bat
start_review_tool.bat --check
run_pipeline.bat scan
start_review_tool.bat
```

macOS：

```bash
./start_review_tool.sh --check
./run_pipeline.sh scan
./start_review_tool.sh
```

扫描成功并输出样本数量后，审核台默认打开 `http://127.0.0.1:8898/`。如果端口被占用，可以修改 `config.json` 中的 `review.port`。macOS 如果不希望自动打开浏览器，可增加 `--no-browser` 参数。

当前默认每个 ROI 一轮只生成一个候选，并执行一次视觉规划和一次语义质检；质量失败会自动反馈并重试一次，仍失败则进入人工审核。开启 `intelligence.parallel_planning` 后，下一张图片的视觉规划可以与当前 CORE 生成重叠执行，但不会同时启动两个 CORE 生图任务。

## 6. 命令行操作

Windows：

```bat
run_pipeline.bat doctor
run_pipeline.bat index-references
run_pipeline.bat scan
run_pipeline.bat generate
run_pipeline.bat generate --queued-only
run_pipeline.bat review
run_pipeline.bat export-approved --output "E:\exports\final_dataset"
```

macOS：

```bash
./run_pipeline.sh doctor
./run_pipeline.sh index-references
./run_pipeline.sh scan
./run_pipeline.sh generate
./run_pipeline.sh generate --queued-only
./run_pipeline.sh review
./run_pipeline.sh export-approved --output "/Users/yourname/exports/final_dataset"
```

在当前发布包缺少 `Anomaly-reference/` 的情况下，只有在另行取得并正确配置参考库后，`index-references` 才能建立有效索引。

API 速度测试工具默认地址为 `http://127.0.0.1:8897/`。

Windows：

```bat
start_api_speed_test.bat
```

macOS：

```bash
./start_api_speed_test.sh
```

macOS 如果端口被占用，可以临时指定其他端口：

```bash
./start_api_speed_test.sh --port 8907
```

## 7. 推荐审核流程

进入网页后，先检查 API 配置并执行连接测试，再确认扫描所得样本已经出现在左侧队列中。随后在样本页核对标签、ROI、Mask 和“下一次送入生成的 ROI”，处理待生成队列，对候选逐个执行通过或驳回，并为被驳回的 ROI 填写明确意见。需要修订的 ROI 可加入重生成队列；全部异常图与 Mask 审核通过后，再导出最终数据集。

## 8. 测试

测试分为 `TEST/ai_tests/` 中的离线自动化测试和 `TEST/manual_tests/` 中面向运行中审核服务的人工接口测试。离线测试使用 Python 标准库 `unittest` 和 Mock，不调用真实 API。

Windows：

```bat
run_pipeline.bat doctor
.venv\Scripts\python.exe -m unittest discover -s TEST\ai_tests -p "test_*.py" -v
```

macOS：

```bash
./run_pipeline.sh doctor
.venv/bin/python -m unittest discover -s TEST/ai_tests -p 'test_*.py' -v
```

`TEST/ai_tests/test_pipeline.py` 包含 22 项 Pipeline 测试，主要覆盖：

- LabelMe 扫描和 Mock 生成；
- 多个 Shape 分成独立 ROI，以及同图 ROI 批量规划；
- 多 ROI 分层生成、顺序合成、审核和导出；
- 前置 ROI 变更后的依赖失效；
- 驳回后自动进入重生成队列；
- 自动重试以及达到上限后转人工审核；
- LLM 规划结果进入 CORE Prompt；
- LLM 语义质检失败及意见回写；
- 多候选生成与比较；
- 参考异常图根据 LabelMe 区域裁剪；
- 知识库 Markdown 注入 Prompt；
- CORE multipart 请求、Alpha Mask 和尺寸归一化；
- 灰度保持、局部色调匹配和拼接边界检测；
- API 配置保存与密钥脱敏；
- 后台队列进度以及规划与生图并行。

`TEST/ai_tests/test_speed_test.py` 包含 2 项速度测试，覆盖默认图与上传图的安全 PNG 转换，以及 HTTP 耗时、状态码、响应字节和 Request ID 统计。

两份测试文件合计 24 项，即 22 项 Pipeline 测试加 2 项速度测试。原发布验证记录为 24 项全部通过，耗时 18.03 秒；不同机器上的实际耗时可能不同。

人工接口测试需要先启动审核后端。具体前置条件和执行方法见 `TEST/manual_tests/README.md`。macOS 首次运行前需要确保脚本可执行：

```bash
chmod +x TEST/manual_tests/run_tests.sh
./TEST/manual_tests/run_tests.sh
```

人工测试应重点验证真实 API 的请求字段、图片顺序、Mask 含义、超时、重试、返回尺寸和灰度一致性。由于离线自动化测试使用 Mock，其通过并不能替代真实 API 验证。

### 重点测试模块

1. **多 ROI 扫描、依赖与合成**：检查同图多框、同标签多框、局部驳回、前置 ROI 重生成和最终合成顺序。
2. **视觉 LLM 与参考图选择**：检查原图、LabelMe、ROI、知识库、参考异常图和历史失败意见是否进入请求，以及规划结果是否合理传递给 CORE。
3. **CORE 请求和图像回传**：使用真实 API 验证请求字段、图片顺序、Mask 含义、超时、重试、返回尺寸和灰度一致性。
4. **Mask、局部合成与像素保持**：检查 ROI 外像素是否保持、边缘是否产生灰度接缝、Mask 是否覆盖真实异常，以及多个 ROI 合成后是否互相破坏。
5. **队列、重试和数据库状态**：测试暂停、中断、失败恢复、重复点击、服务重启，以及“进行中—待审—重生成—通过”的状态转换。

## 9. 项目结构

```text
项目根目录/
├── anomaly_factory/                 核心程序与网页前端
│   ├── cli.py                       scan、generate、review、export 等命令入口
│   ├── config.py                    配置、路径和 API 凭据管理
│   ├── labelme.py                   LabelMe 解析及 ROI/Mask 生成
│   ├── knowledge.py                 知识库读取与 Prompt 组装
│   ├── reference_index.py           异常参考图索引
│   ├── intelligence.py              视觉 LLM 规划、候选比较和语义质检
│   ├── core.py                      CORE 生图 API 适配器
│   ├── pipeline.py                  生成、合成、自检和导出流程
│   ├── db.py                        SQLite 状态、审核和尝试记录
│   ├── review_server.py             审核服务和后台生成队列
│   ├── speed_test_server.py         API 速度测试服务
│   ├── static/                      审核页面前端
│   └── speed_test_static/           速度测试页面前端
├── knowledge-bank/                  标签、Prompt、异常知识和反馈规则
├── TEST/
│   ├── ai_tests/                    离线自动化测试（22 + 2 项）
│   │   ├── test_pipeline.py
│   │   └── test_speed_test.py
│   └── manual_tests/                面向运行中审核服务的人工接口测试
│       ├── README.md
│       └── run_tests.sh
├── config.json                      主配置
├── requirements.txt                 Python 依赖
├── setup_env.bat                    Windows 环境安装
├── run_pipeline.bat                 Windows 命令行入口
├── start_review_tool.bat             Windows 审核台入口
├── start_api_speed_test.bat          Windows API 测速入口
├── setup_env.sh                     macOS/Linux 环境安装
├── run_pipeline.sh                  macOS/Linux 命令行入口
├── start_review_tool.sh              macOS/Linux 审核台入口
├── start_api_speed_test.sh           macOS/Linux API 测速入口
├── python_path.local.txt             本机 Python 路径，运行安装脚本后生成
├── api_credentials.local.json        本机 API 凭据，通过网页保存后生成
└── 中间产物/                         数据库、候选图和审核结果，运行后生成
```

`Anomaly-reference/` 未列入上述发布包结构，因为当前仓库不包含该目录；取得参考库后可将其放在项目根目录，或通过 `config.json` 指向其他位置。`CORE_INTEGRATION.md` 同样不在当前发布包中，任何 API 接口差异都应以实际网关文档和 `config.json` 为准。


### 人工测试



### 测试AI



### AI测试

[test_pipeline.py](D:/Workshop/update/20260811/pipeline_v2/tests/test_pipeline.py) 有22项测试，主要覆盖：
- LabelMe扫描和Mock生成。
- 多个Shape拆成独立ROI。
- 同图ROI批量规划。
- 多ROI分层生成、合成、审核和导出。
- 顺序生成时，上一个ROI作为下一个ROI的基础。
- 前置ROI变更后的依赖失效。
- 驳回后自动进入重生成队列。
- 自动重试、达到上限后转人工审核。
- LLM规划结果进入CORE Prompt。
- LLM语义质检失败及意见回写。
- 多候选生成与比较。
- 参考异常图根据LabelMe区域裁剪。
- 知识库Markdown注入Prompt。
- CORE multipart请求、Alpha Mask和尺寸归一化。
- 灰度保持、局部色调匹配、拼接边界检测。
- API配置保存和密钥脱敏。
- 后台队列进度和规划/生图并行。
[test_speed_test.py](D:/Workshop/update/20260811/pipeline_v2/tests/test_speed_test.py) 有2项测试：
- 默认图和上传图是否安全转换为PNG。
- HTTP耗时、状态码、响应字节和Request ID统计。
- 
codex实际运行了全部测试：24项全部通过，耗时18.03秒。

