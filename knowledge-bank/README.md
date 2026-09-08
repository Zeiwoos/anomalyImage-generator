# 工业异常图像生成知识库（学习库2）

本知识库只允许从项目内的 `Anomaly-reference/` 学习异常外观、部件关系和 LabelMe 标签语义。该目录是“学习库2”，也是当前唯一允许使用的异常参考源。

## 防止数据泄露

- 禁止检索、读取、提示或引用任何未登记的历史异常库、测试集或审核集。
- 旧参考路径不得出现在提示词、索引、配置、日志或模型输入中。
- 待处理数据集只能作为被编辑对象，不能自动回流到学习库。
- 只有用户明确批准并迁入 `Anomaly-reference/` 的样本，才可成为后续参考。
- 参考图只用于学习异常形态；输出不得复制参考图的设备身份、背景纹理或局部像素。

## 阅读顺序

1. `00_source_policy.md`：语料边界和统计。
2. `01_global_rules.md`：所有标签共用的反事实编辑原则。
3. `02_label_taxonomy.md`：主标签、补充标签、别名与程序语义。
4. `03_missing.md`～`07_reverse_installation.md`：按异常族学习物理规律。
5. `08_prompt_protocol.md`：外层程序如何为 CORE 组装任务。
6. `09_quality_gate.md`：自动检查与人工审核门槛。
7. `10_review_regeneration.md`：审核意见到再生成约束的映射。
8. `11_paired_labelme_dataset.md`：故障—正常配对结构、多框拆分及补充标签协议。

程序使用 `labels.json`、`feedback_rules.json`、自动生成的 `reference_index.json`，并把全局规则、对应异常家族规则、Prompt 协议和质量门槛 Markdown 直接注入视觉 LLM 与 CORE 的基础 Prompt。JSON 标签优先于目录名；目录只作为辅助信息。
