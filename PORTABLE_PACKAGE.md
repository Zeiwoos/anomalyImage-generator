# 可迁移发布包说明

版本：pipeline_v2 改良交付版（2026-08-11）

本目录由开发工作区复制并清理得到，目标是允许其他用户在不同 Windows 计算机上直接配置和运行。

发布包保留：程序源码、静态网页、测试、知识库、异常参考库、通用配置模板、启动脚本、性能说明和完整流程分析。

发布包排除：业务数据集、生成中间产物、SQLite 数据库、人工审核表、下载文件、缓存、虚拟环境、固定 Conda/Python 路径、真实 API URL 与 API Key、个人对话记录。

首次使用必须完成三项本机配置：

1. Python：运行 `setup_env.bat`，或设置 `PIPELINE_PYTHON`；
2. 数据集：填写 `config.json > dataset.root`；
3. API：在网页“API 配置”中填写，或设置 `PIPELINE_API_BASE_URL`、`PIPELINE_API_KEY`。

共享此目录前，应再次确认不存在 `api_credentials.local.json`、`python_path.local.txt` 和 `中间产物/`。

本版默认使用单候选快速平衡模式，并启用视觉规划单步前瞻并行。客户可在审核台“API与智能策略”中调整 CORE 质量、候选数、自动重试次数和并行规划开关。
