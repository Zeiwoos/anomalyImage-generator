# 学习库2：来源、结构与使用边界

## 唯一来源

参考根目录为项目相对路径 `Anomaly-reference/`。项目迁移到其他机器时只需保持此目录名，不依赖绝对盘符。

当前实际目录统计：

- 异常图片：61 张；
- LabelMe JSON：61 个；
- 唯一标签：22 个；
- 标注 shape：65 个；
- shape 类型：polygon 33 个、rectangle 32 个；
- 全部图像为灰度视觉域，彩色 ROI 框没有烧录进图像像素。

`故障-正常图匹配数据介绍文档.md` 定义了未来完整配对格式：叶目录含 `00_fault.jpg/json`，并可含 `01_normal.jpg/json`、`02_normal.jpg/json` 等多个正常图。程序按同一叶目录与同一标签建立故障—正常匹配。当前实际目录尚未放入 `*_normal` 文件，因此索引会如实记录 `fault_image_count=61`、`normal_image_count=0`，不得回退到旧测试集补参考。

## LabelMe 的正确用法

- `shape.label` 决定异常类别和提示词。
- `shape.points` 与 `shape_type` 决定异常发生位置和允许编辑范围。
- 标签语义始终由 `shape.label` 决定，不能用框线颜色猜类别。
- 程序给 CORE 的输入是源图、当前 shape 的独立二值 ROI mask、标签对应提示词。若源图像素确实烧录了框线或标签文字，则在有限 ROI 内同步无痕去除；若只是 LabelMe 的显示元数据，则不做不存在的“去框”重绘。
- 一个 JSON 可以有多个 shape 或多个标签。默认 `per_shape`：每个 shape 独立生成、审核、重生成和产出 mask，禁止把随机附加的其他异常框一起生成。
- 无 shape 的 JSON 应进入人工确认队列，不能猜测位置后自动生成。

## 已知标注例外

- `DiuShi/ZhaPian` 有样本同时包含 `DS_ZP` 与 `DS_KKX`，属于同图多实例/多标签。
- `SongTuo/YouDu` 中有一份 JSON 使用 `ST_LM`；程序按 JSON 标签处理并记录目录冲突告警。
- `DiuShi/LuoMu` 中有一份 JSON 没有 shape；程序必须暂停该样本。
- `ZhaPianFanZhuang` 的 JSON 标签为 `KKX_FZ`；按补充说明解释为开口销翻转，目录名只留作审计信息。

## 参考图使用原则

参考索引按标签选择 1～3 个相对路径。外层程序先把参考中的规律翻译成明确提示词；只有 CORE 支持多参考输入时，才附带参考图片。参考图不能取代源图，不能把参考设备的结构或背景复制到源图。
