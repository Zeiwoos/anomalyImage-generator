# 故障—正常配对数据与多框任务协议

本文件把 `Anomaly-reference/故障-正常图匹配数据介绍文档.md` 转换为外层程序和 CORE 都能稳定遵循的任务规则；原说明文档仍是字段含义的事实来源。

## 叶目录结构

- `00_fault.jpg/json`：真实故障图及其 LabelMe 标注；
- `01_normal.jpg/json`、`02_normal.jpg/json`……：与故障图对应的正常图及候选 ROI；
- 图像与同名 JSON 必须配对，语义取自 `shapes[].label`，位置取自 `points` 与 `shape_type`。

当前 `Anomaly-reference` 实际只有 61 对 `*_fault` 图/JSON、没有 `*_normal` 文件。程序只索引现有文件，并在未来正常图补入同一叶目录后自动建立同标签匹配；禁止回退到旧测试集寻找正常图。

## 一个正常样本多个框

正常 JSON 可能包含当前目录类别的一个 ROI，并随机附加 1～2 个其他异常类别 ROI。这些框不是要求在一张图中同时生成多个异常，而是多个独立生成机会。

默认规则为 `per_shape`：

1. 每个 shape 生成独立 `sample_id`；
2. 只把当前 shape 的二值 mask、标签规则和参考图交给 CORE；
3. 候选图、审核意见、再生成版本和最终精细 mask 都按 shape 隔离；
4. 一个框被驳回不影响同源图的其他框；
5. 仅在配置显式设为 `joint` 时才允许合并，但常规生产不建议这样做。

## 框线处理

标签语义不能从框线颜色推断。若彩框只存在于 LabelMe 显示层，则输入原图没有框，不执行额外去框；若框线或标签文字确实已烧录进源图像素，则应在当前 padded ROI 内先无痕恢复原表面，再完成对应异常，不能留下彩线、文字或扩大背景重绘。

## 补充标签

- 别名：`DA_ZP→DS_ZP`、`YW_HeiJiaoDai→S_HeiJiaoDai`、`YW_SuLiao→S_SuLiao`、`YW_ZhiTuan→S_BaiZhiTuan`；
- 新规则：`PSTQ_CLXDB` 为齿轮箱挡板局部破损脱漆；
- `KKX_FZ` 为开口销翻转；
- `FSTS` 按正常图中被框选的防松铁丝生成“防松铁丝丢失”：只移除铁丝，完整保留螺栓、垫圈、孔位与安装面。
