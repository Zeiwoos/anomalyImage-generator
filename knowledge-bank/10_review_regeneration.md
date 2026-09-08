# 审核意见驱动的程序化再生成

审核界面使用结构化原因码＋可选自由文本。原因码由外层程序翻译成明确的修正约束，自由文本作为补充，不要求 Codex 人工介入。

常用原因码：

| 原因码 | 程序动作 |
|---|---|
| `ANOMALY_TOO_SMALL` | 增加异常可见范围，但不越过允许区域 |
| `ANOMALY_TOO_WEAK` | 增强局部对比、形态证据和可识别性 |
| `WRONG_STRUCTURE` | 强调保留安装逻辑，禁止臆造结构，从干净源图重做 |
| `PARTIAL_REMOVAL` | 沿目标零件完整真实轮廓移除，清除残留悬空边缘 |
| `BACKGROUND_CHANGED` | 强化域外零改动并缩小实际合成范围 |
| `COLOR_SHIFT` | 强制灰度归一化并禁止 RGB 色偏 |
| `EDGE_ARTIFACT` | 修复硬边、光晕、拼贴和模糊过渡 |
| `ROI_MISALIGNED` | 暂停自动再生成，要求人工修正 LabelMe ROI |
| `OIL_TOO_SMALL` | 扩大相连油膜/流痕/积油，而非只加深小黑点 |
| `OIL_LOOKS_LIKE_SHADOW` | 增加湿润反光、浸润边缘和油膜内部层次 |
| `MASK_TOO_COARSE` | 重新从差异生成精细 mask，降低矩形 ROI 继承 |
| `MASK_MISSING_AREA` | 扩张缺失区域或由人工画笔补齐 |
| `MASK_EXTRA_AREA` | 收缩 mask，排除未变化纹理和背景 |

再生成状态流：`异常待审 → 驳回/重生成排队 → 新版本待审 → 异常通过 → Mask待审/修改 → 全部通过`。

