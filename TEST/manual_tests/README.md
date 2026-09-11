# anomalyImage-generator 手工接口测试框架

该目录用于编写针对 anomalyImage-generator 审核后端的接口与流程测试。框架只使用 Python 标准库，不需要额外安装 pytest 或 requests。

## 快速开始

1. 在项目根目录配置并扫描数据集：

   ```bat
   run_pipeline.bat scan
   ```

2. 启动审核后端：

   ```bat
   start_review_tool.bat
   ```

3. 在另一个终端运行测试：

   ```bat
   TEST\manual_tests\run_tests.bat
   ```

默认测试地址是 `http://127.0.0.1:8898`。如果后端使用了其他端口，将 `config.example.json` 复制为 `config.local.json` 后修改 `base_url`。`config.local.json` 不应提交到版本库。

也可以临时指定地址：

```bat
set "ANOMALY_TEST_BASE_URL=http://127.0.0.1:8900"
TEST\manual_tests\run_tests.bat
```

## 编写用例

复制 `case_template.py`，并改名为 `test_模块名.py`。默认发现规则为 `test_*.py`；原来的空文件 `test.py` 不会被自动执行。

```python
from base import ManualApiTestCase


class MyApiTest(ManualApiTestCase):
    def test_health(self):
        payload = self.client.get_json("/api/health")
        self.assertTrue(payload["ok"])
```

运行单个文件：

```bat
TEST\manual_tests\run_tests.bat test_api_smoke.py
```

运行匹配的一组文件：

```bat
TEST\manual_tests\run_tests.bat "test_multi_roi*.py"
```

每次执行会在 `reports/` 中生成带时间戳的文本报告。

## 已提供的能力

- `api_client.py`：GET/POST JSON、二进制下载、HTTP错误诊断和Worker轮询。
- `base.py`：统一读取配置，并在后端不可达时给出明确失败信息。
- `test_api_smoke.py`：只读冒烟测试，不改变数据集或审核状态。
- `case_template.py`：包含只读、队列及审核接口示例；写操作示例默认跳过。
- `runner.py`：测试发现、运行、控制台输出及报告保存。

## 安全边界

以下接口会改变状态，写用例时应使用专门的测试数据集：

- `POST /api/run-queue`
- `POST /api/generation-feedback`
- `POST /api/review`、`POST /api/review-batch`
- `POST /api/mask`
- `POST /api/api-settings`
- `POST /api/delete-sample`

其中 `/api/delete-sample` 会移动整个样本目录。除非测试数据可丢弃且已验证 `sample_id`，不要在普通测试中调用。

