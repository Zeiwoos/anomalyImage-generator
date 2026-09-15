# 异常图像生成与审核系统

## 一、运行系统

以下命令均在项目根目录执行。需要 Python 3.10 或更高版本。

### 1. 安装环境

Windows（PowerShell 或 CMD）：

```powershell
.\setup_env.bat
```

macOS / Linux：

```bash
bash setup_env.sh
```

安装脚本会创建 `.venv` 并安装依赖。已有 Conda 环境时，也可以激活该环境后运行 `python -m pip install -r requirements.txt`，并将 `python_path.local.txt` 设置为该环境的 Python 解释器完整路径。

### 2. 配置数据与参考库

修改 `config.json` 中的 `dataset.root`，指向包含图片和 LabelMe JSON 标注的数据集目录。只修改对应字段，不要用下面的片段覆盖整个配置文件：

```json
"dataset": {
  "root": "D:/datasets/my_labelme_dataset"
}
```

Windows 路径建议使用 `/`；macOS / Linux 使用实际绝对路径，例如 `/home/user/datasets/my_labelme_dataset`。

将参考图库放入 `Anomaly-reference/`，或将 `project.reference_root` 改为实际参考库路径。使用参考图库时，在启动前建立索引：

```powershell
.\run_pipeline.bat index-references
```

macOS / Linux 对应命令为 `bash run_pipeline.sh index-references`。

### 3. 扫描并启动审核网页

Windows：

```powershell
.\start_review_tool.bat --check
.\run_pipeline.bat scan
.\start_review_tool.bat
```

macOS / Linux：

```bash
bash start_review_tool.sh --check
bash run_pipeline.sh scan
bash start_review_tool.sh
```

默认地址为 **http://127.0.0.1:8898/**，端口由 `config.json` 中的 `review.port` 配置。启动脚本不会自动扫描；首次使用、增加或修改标注后，需要重新执行 `scan`。

网页操作顺序：

1. 打开“API 配置”，填写所用服务的 Base URL、API Key 和模型配置，保存并测试连接。凭据保存在本机的 `api_credentials.local.json`。
2. 选择待处理样本和区域，启动生成队列。实际生成需要可用的 API，可能产生费用。
3. 审核生成的异常图；通过后继续审核 Mask，驳回时填写反馈并重新生成。
4. 全部审核通过后导出数据。也可以使用命令：

```powershell
.\run_pipeline.bat export-approved --output "D:/exports/final_dataset"
```

macOS / Linux 使用 `bash run_pipeline.sh export-approved --output "/home/user/exports/final_dataset"`，并替换为实际导出目录。

如需打开独立的 API 测速网页，Windows 运行 `.\start_api_speed_test.bat`，macOS / Linux 运行 `bash start_api_speed_test.sh`，默认地址为 **http://127.0.0.1:8897/**。

在启动服务的终端按 `Ctrl+C` 停止服务。

## 二、运行单元测试

### 1. 选择测试环境

测试使用 Python 标准库 `unittest`，部分用例会启动临时本地 HTTP 服务。测试会自行创建临时图片、标注和数据库，**不需要提前启动系统、不需要准备业务图片或配置真实 API**；外部模型调用使用模拟响应。

以下命令中的 `python` 必须指向已安装项目依赖的环境。若使用安装脚本创建的环境，先激活：

Windows PowerShell：

```powershell
.\.venv\Scripts\Activate.ps1
```

Windows CMD：

```bat
.venv\Scripts\activate.bat
```

macOS / Linux：

```bash
source .venv/bin/activate
```

也可以不激活，直接将下文的 `python` 替换为 `.venv\Scripts\python.exe`（Windows）或 `.venv/bin/python`（macOS / Linux）。使用 PyCharm 时，选择同一个解释器后运行相应测试入口即可。

### 2. 运行人工编写的测试

| 范围 | 测试根目录业务代码 | 测试修复副本 |
|---|---|---|
| 全部 38 个用例 | `python TEST/manual_tests/run_tests.py` | `python TEST/manual_tests/run_tests_fixed.py` |
| gys：18 个用例 | `python TEST/manual_tests/run_gys.py` | `python TEST/manual_tests/run_gys_fixed.py` |
| zyc：20 个用例 | `python TEST/manual_tests/run_zyc.py` | `python TEST/manual_tests/run_zyc_fixed.py` |

普通入口加载根目录的 `anomaly_factory/`；`_fixed.py` 入口加载 `TEST/_shared/fix_candidates/anomaly_factory/`。两者运行同一批用例，只切换被测业务代码。普通入口不会自动找回历史版本，结果取决于根目录当前代码。

只查看用例列表：

```bash
python TEST/manual_tests/run_tests.py --list
```

单独运行一个测试文件中的用例（加载根目录业务代码）：

```bash
python -m unittest TEST.manual_tests.test_feedback -v
```

### 3. 查看测试结果

- `ok`：该用例的全部断言通过。
- `FAIL`：实际行为不符合预期；在修复前版本上，缺陷用例失败是缺陷复现结果。
- `ERROR`：用例运行中发生未被正常处理的异常，需要查看错误堆栈。

根目录保持修复前代码时，全部人工测试应为 **33 个通过、5 个失败**，失败用例为 D01、D02、D02b、D03、D03b。修复副本的通过数量取决于其中已经合入哪些修复；仅包含 gys 修复时，D03、D03b 仍会失败。

上述运行入口会把报告写入 `TEST/manual_tests/reports/<all、gys 或 zyc>/<baseline 或 candidate>/results.json`。其中 `baseline` 对应根目录代码，`candidate` 对应修复副本；`loaded_source` 字段记录实际加载的源文件。同一入口再次运行会覆盖对应报告。
