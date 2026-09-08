from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List


FAMILY_DOCUMENTS = {
    "missing": "03_missing.md",
    "oil_leak": "04_oil_leak.md",
    "loose": "05_loose.md",
    "foreign_object": "06_foreign_objects.md",
    "reverse_installation": "07_reverse_installation.md",
}


class KnowledgeBase:
    def __init__(self, root: Path, reference_root: Path) -> None:
        self.root = root.resolve()
        self.reference_root = reference_root.resolve()
        self.labels_payload = json.loads((self.root / "labels.json").read_text(encoding="utf-8"))
        self.feedback = json.loads((self.root / "feedback_rules.json").read_text(encoding="utf-8"))
        self.labels: Dict[str, Dict[str, Any]] = self.labels_payload["labels"]
        self.aliases: Dict[str, str] = self.labels_payload.get("aliases", {})
        index_path = self.root / "reference_index.json"
        self.reference_index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.is_file() else {"labels": {}}
        self._document_cache: Dict[str, str] = {}

    def validate_labels(self, labels: Iterable[str]) -> List[str]:
        return [label for label in labels if self.resolve_label(label) not in self.labels]

    def resolve_label(self, code: str) -> str:
        return str(self.aliases.get(code, code))

    def label(self, code: str) -> Dict[str, Any]:
        code = self.resolve_label(code)
        if code not in self.labels:
            raise KeyError("知识库没有标签：{}".format(code))
        return self.labels[code]

    def _document(self, name: str) -> str:
        if name not in self._document_cache:
            path = self.root / name
            self._document_cache[name] = path.read_text(encoding="utf-8").strip() if path.is_file() else ""
        return self._document_cache[name]

    def knowledge_context(self, labels: Iterable[str]) -> str:
        """Return compact, label-specific bank instructions that actually reach the LLM and CORE."""
        families: List[str] = []
        for code in labels:
            family = str(self.label(code).get("family") or "")
            if family and family not in families:
                families.append(family)
        documents = ["01_global_rules.md"]
        documents.extend(FAMILY_DOCUMENTS[family] for family in families if family in FAMILY_DOCUMENTS)
        documents.extend(["08_prompt_protocol.md", "09_quality_gate.md"])
        blocks = [self._document(name) for name in documents]
        return "\n\n".join(block for block in blocks if block)

    def reference_examples(self, labels: Iterable[str], limit: int) -> List[Dict[str, Any]]:
        """Resolve reference image, annotation file and matching anomaly geometry together."""
        if limit <= 0:
            return []
        output: List[Dict[str, Any]] = []
        seen = set()
        for raw_label in labels:
            label = self.resolve_label(raw_label)
            label_count = 0
            for raw in self.reference_index.get("labels", {}).get(label, []):
                row = raw if isinstance(raw, dict) else {"image": raw}
                rel = row.get("image")
                if not rel:
                    continue
                image_path = (self.reference_root / str(rel)).resolve()
                try:
                    image_path.relative_to(self.reference_root)
                except ValueError:
                    continue
                if not image_path.is_file() or image_path in seen:
                    continue
                json_path = None
                if row.get("json"):
                    candidate = (self.reference_root / str(row["json"])).resolve()
                    try:
                        candidate.relative_to(self.reference_root)
                    except ValueError:
                        candidate = None
                    if candidate is not None and candidate.is_file():
                        json_path = candidate
                shapes: List[Dict[str, Any]] = []
                if json_path is not None:
                    try:
                        payload = json.loads(json_path.read_text(encoding="utf-8-sig"))
                        for index, shape in enumerate(payload.get("shapes") or []):
                            if not isinstance(shape, dict):
                                continue
                            shape_label = self.resolve_label(str(shape.get("label") or ""))
                            if shape_label == label:
                                shapes.append(
                                    {
                                        "index": index,
                                        "label": str(shape.get("label") or ""),
                                        "shape_type": str(shape.get("shape_type") or "polygon"),
                                        "points": shape.get("points") or [],
                                    }
                                )
                    except (OSError, ValueError, TypeError, json.JSONDecodeError):
                        shapes = []
                seen.add(image_path)
                output.append(
                    {
                        "image": image_path,
                        "json": json_path,
                        "label": label,
                        "shapes": shapes,
                        "source": "reference_bank",
                    }
                )
                label_count += 1
                if label_count >= limit:
                    break
        return output

    def reference_paths(self, labels: Iterable[str], limit: int) -> List[Path]:
        return [row["image"] for row in self.reference_examples(labels, limit)]

    def feedback_instructions(self, stage: str, reason_codes: Iterable[str]) -> List[str]:
        rules = self.feedback.get(stage, {})
        return [str(rules[code]) for code in reason_codes if code in rules]

    def build_prompt(
        self,
        labels: Iterable[str],
        attempt: int,
        reason_codes: Iterable[str] = (),
        comment: str = "",
    ) -> str:
        labels = list(labels)
        sections = [
            "任务：在输入的工业设备完整图像上执行局部反事实异常编辑。",
            "LabelMe 标注给出异常语义的重点位置，不是异常硬边界；透明编辑 mask 是更宽的上下文允许区。必须先理解完整源图结构，再在物理需要时让异常及其直接影响自然越过标注框，但不得越过编辑 mask 或改变无关内容。",
            "若源图像素中确实烧录了 ROI 线或标签文字，须在允许区内无痕去除后再生成异常；若标注只存在于 JSON 中，则禁止额外重绘。",
            "输出必须与输入同尺寸、同视角、同构图、同成像域。除异常及其直接局部影响外，所有像素对应的视觉内容保持不变。",
            "源图为灰度视觉时，输出必须严格保持灰度，不得出现 RGB 色偏；禁止文字、框线、mask 可视化、水印或说明。",
        ]
        for code in labels:
            canonical = self.resolve_label(code)
            row = self.label(canonical)
            display = code if canonical == code else "{}→{}".format(code, canonical)
            sections.append("标签 {}（{}）：{}。".format(display, row["name_zh"], "；".join(row["rules"])))
            sections.append("该标签禁止：{}。".format("；".join(row["forbidden"])))
        bank = self.knowledge_context(labels)
        if bank:
            sections.append("以下知识库规则已经过人工样本归纳，必须用于本次实例推理：\n---\n{}\n---".format(bank))
        sections.append("参考图片只用于理解异常本体的材质、形态和机械关系；禁止复制参考设备、背景、纹理或身份特征到源图。")
        sections.append("反事实自检：若移除所有新增异常，必须能恢复干净源图；禁止矩形曝光块、灰度接缝、整块重绘或与异常无关的结构变化。")
        sections.append("仅返回编辑后的完整图像。")
        feedback = self.feedback_instructions("anomaly", reason_codes)
        if attempt > 1:
            sections.append("这是第{}次尝试。必须从干净源图重新编辑，不能在上一版候选上累积修改。".format(attempt))
        if feedback:
            sections.append("本轮必须修正：{}".format(" ".join(feedback)))
        if comment.strip():
            sections.append("审核员补充说明：{}".format(comment.strip()[:2000]))
        return "\n\n".join(sections) + "\n"
