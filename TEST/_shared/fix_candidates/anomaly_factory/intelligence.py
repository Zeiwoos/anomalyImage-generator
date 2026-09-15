from __future__ import annotations

import base64
import io
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urljoin

from PIL import Image, ImageChops, ImageFilter

from .config import load_claude_environment
from .core import _http_opener


class IntelligenceTransportError(RuntimeError):
    """Retryable transport failure before a usable vision-agent response."""

    retryable = True

    def __init__(self, message: str, attempts: int = 1, errors: Optional[List[str]] = None) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.errors = list(errors or [])


MASK_REGION_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "shape": {"type": "string", "enum": ["polygon", "rectangle", "ellipse"]},
        "points": {
            "type": "array",
            "items": {
                "type": "array", "items": {"type": "number"},
                "minItems": 2, "maxItems": 2,
            },
            "minItems": 2,
        },
        "padding_px": {"type": "integer", "minimum": 0, "maximum": 256},
        "purpose": {"type": "string"},
    },
    "required": ["shape", "points", "padding_px", "purpose"],
}


PLANNER_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "edit_instruction": {"type": "string"},
        "target_description": {"type": "string"},
        "expected_background": {"type": "string"},
        "must_preserve": {"type": "array", "items": {"type": "string"}},
        "anomaly_strength": {"type": "string", "enum": ["subtle", "clear", "alarm"]},
        "mask_assessment": {"type": "string"},
        "warnings": {"type": "array", "items": {"type": "string"}},
        "generation_mode": {"type": "string", "enum": ["focused_context", "broad_context"]},
        "edit_context_scale": {"type": "string", "enum": ["tight", "normal", "wide", "very_wide"]},
        "selected_reference_indices": {"type": "array", "items": {"type": "integer"}},
        "retry_action": {"type": "string", "enum": ["initial", "refine_prompt", "switch_reference", "expand_context", "tighten_context", "structural_reanalysis"]},
        "strategy_summary": {"type": "string"},
        "scene_analysis": {"type": "string"},
        "physical_anchor": {"type": "string"},
        "reference_rationale": {"type": "string"},
        "negative_patterns_to_avoid": {"type": "array", "items": {"type": "string"}},
        "background_preservation_plan": {"type": "string"},
        "mask_geometry": {"type": "string", "enum": ["agent_regions", "focus_dilation", "rounded_context"]},
        "mask_regions": {"type": "array", "items": MASK_REGION_SCHEMA},
        "protected_regions": {"type": "array", "items": MASK_REGION_SCHEMA},
        "candidate_directives": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "edit_instruction", "target_description", "expected_background", "must_preserve",
        "anomaly_strength", "mask_assessment", "warnings",
        "generation_mode", "edit_context_scale", "selected_reference_indices", "retry_action", "strategy_summary",
        "scene_analysis", "physical_anchor", "reference_rationale", "negative_patterns_to_avoid",
        "background_preservation_plan",
        "mask_geometry", "mask_regions", "protected_regions", "candidate_directives",
    ],
}


BATCH_PLANNER_ITEM_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"roi_id": {"type": "string"}, **PLANNER_SCHEMA["properties"]},
    "required": ["roi_id", *PLANNER_SCHEMA["required"]],
}


BATCH_PLANNER_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "shared_scene_analysis": {"type": "string"},
        "shared_preservation_constraints": {"type": "array", "items": {"type": "string"}},
        "roi_plans": {"type": "array", "items": BATCH_PLANNER_ITEM_SCHEMA, "minItems": 1},
    },
    "required": ["shared_scene_analysis", "shared_preservation_constraints", "roi_plans"],
}


COMPARISON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "selected_index": {"type": "integer"},
        "pass": {"type": "boolean"},
        "reason_codes": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    "ANOMALY_TOO_SMALL", "ANOMALY_TOO_WEAK", "WRONG_LABEL", "WRONG_STRUCTURE",
                    "PARTIAL_REMOVAL", "BACKGROUND_CHANGED", "COLOR_SHIFT", "EDGE_ARTIFACT",
                    "OIL_TOO_SMALL", "OIL_LOOKS_LIKE_SHADOW", "OTHER",
                ],
            },
        },
        "candidate_scores": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "index": {"type": "integer"},
                    "score": {"type": "integer"},
                    "strength": {"type": "string"},
                    "physical_realism": {"type": "string"},
                    "background_fidelity": {"type": "string"},
                    "key_issue": {"type": "string"},
                },
                "required": ["index", "score", "strength", "physical_realism", "background_fidelity", "key_issue"],
            },
        },
        "selection_rationale": {"type": "string"},
        "diagnosis": {"type": "string"},
        "revision_instruction": {"type": "string"},
        "next_strategy": {
            "type": "string",
            "enum": ["keep", "change_reference", "tighten_mask", "expand_mask", "simplify_edit", "structural_reanalysis"],
        },
    },
    "required": [
        "selected_index", "pass", "reason_codes", "candidate_scores", "selection_rationale",
        "diagnosis", "revision_instruction", "next_strategy",
    ],
}


CRITIC_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "pass": {"type": "boolean"},
        "severity": {"type": "string", "enum": ["none", "minor", "major"]},
        "reason_codes": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    "ANOMALY_TOO_SMALL", "ANOMALY_TOO_WEAK", "WRONG_LABEL", "WRONG_STRUCTURE",
                    "PARTIAL_REMOVAL", "BACKGROUND_CHANGED", "COLOR_SHIFT", "EDGE_ARTIFACT",
                    "OIL_TOO_SMALL", "OIL_LOOKS_LIKE_SHADOW", "OTHER",
                ],
            },
        },
        "diagnosis": {"type": "string"},
        "revision_instruction": {"type": "string"},
        "background_seam_detected": {"type": "boolean"},
        "looks_like_normal_installation": {"type": "boolean"},
        "counterfactual_consistency": {"type": "string"},
    },
    "required": [
        "pass", "severity", "reason_codes", "diagnosis", "revision_instruction",
        "background_seam_detected", "looks_like_normal_installation", "counterfactual_consistency",
    ],
}


def _json_from_text(value: str) -> Dict[str, Any]:
    text = value.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("LLM响应中没有JSON对象")
        payload = json.loads(text[start:end + 1])
    if not isinstance(payload, dict):
        raise ValueError("LLM响应JSON根节点不是object")
    return payload


def _response_text(payload: Dict[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    chunks: List[str] = []
    for item in payload.get("output", []) if isinstance(payload, dict) else []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []) or []:
            if isinstance(content, dict) and content.get("type") == "output_text" and isinstance(content.get("text"), str):
                chunks.append(content["text"])
    if not chunks:
        raise ValueError("Responses API未返回output_text")
    return "\n".join(chunks)


def _image_data_url(path: Path, maximum: int = 1536) -> str:
    with Image.open(path) as opened:
        image = opened.convert("L") if opened.mode in {"1", "L", "I", "I;16", "F"} else opened.convert("RGB")
        if max(image.size) > maximum:
            scale = maximum / max(image.size)
            image = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def build_roi_context(
    source_path: Path,
    roi_mask_path: Path,
    output_path: Path,
    focus_mask_path: Optional[Path] = None,
) -> Path:
    """Create a global locator view with separate focus and editable context."""
    with Image.open(source_path) as opened:
        source = opened.convert("RGB")
    with Image.open(roi_mask_path) as opened:
        roi = opened.convert("L").point(lambda value: 255 if value >= 128 else 0, mode="L")
    if roi.size != source.size:
        raise ValueError("智能分析ROI尺寸与源图不一致")
    dimmed = source.point(lambda value: round(value * 0.28))
    context = Image.composite(source, dimmed, roi)
    outer = roi.filter(ImageFilter.MaxFilter(7))
    inner = roi.filter(ImageFilter.MinFilter(7))
    edit_boundary = ImageChops.subtract(outer, inner)
    context.paste((255, 176, 40), mask=edit_boundary)
    if focus_mask_path is not None:
        with Image.open(focus_mask_path) as opened:
            focus = opened.convert("L").point(lambda value: 255 if value >= 128 else 0, mode="L")
        if focus.size != source.size:
            raise ValueError("LabelMe关注区尺寸与源图不一致")
        focus_outer = focus.filter(ImageFilter.MaxFilter(9))
        focus_inner = focus.filter(ImageFilter.MinFilter(5))
        focus_boundary = ImageChops.subtract(focus_outer, focus_inner)
        context.paste((0, 255, 80), mask=focus_boundary)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    context.save(output_path, format="PNG", optimize=True)
    return output_path


class VisionLLMClient:
    """Small Responses API client used only for planning and semantic review."""

    def __init__(self, config: Dict[str, Any]) -> None:
        self.root_config = config
        core = dict(config.get("core") or {})
        intelligence = dict(config.get("intelligence") or {})
        self.config = {**core, **intelligence}
        self.runtime_env = load_claude_environment(config)
        base_env = str(self.config.get("base_url_env") or "")
        self.base_url = str(self.config.get("base_url") or self.runtime_env.get(base_env, "")).strip().rstrip("/") + "/"
        if self.base_url == "/":
            raise ValueError("未配置智能LLM base_url")
        key_env = str(self.config.get("api_key_env") or "")
        self.api_key = self.runtime_env.get(key_env, "") or os.environ.get(key_env, "")
        if not self.api_key:
            raise ValueError("环境中没有智能LLM API密钥：{}".format(key_env))
        self.opener = _http_opener(self.config, self.runtime_env, self.base_url)

    @property
    def enabled(self) -> bool:
        return bool(self.root_config.get("intelligence", {}).get("enabled", False))

    def _url(self) -> str:
        endpoint = str(self.config.get("endpoint") or "/v1/responses")
        return endpoint if endpoint.startswith(("http://", "https://")) else urljoin(self.base_url, endpoint.lstrip("/"))

    def _headers(self) -> Dict[str, str]:
        header = str(self.config.get("auth_header") or "Authorization")
        scheme = str(self.config.get("auth_scheme") or "Bearer").strip()
        return {"Accept": "application/json", "Content-Type": "application/json", header: "{} {}".format(scheme, self.api_key).strip()}

    def _request(self, body: Dict[str, Any]) -> Dict[str, Any]:
        url = self._url()
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request_started = time.monotonic()
        attempts = max(1, min(10, int(self.config.get("transport_retries") or 4)))
        backoff = max(0.0, float(self.config.get("transport_retry_backoff_seconds") or 2))
        retryable_statuses = {408, 409, 425, 429, 500, 502, 503, 504}
        errors: List[str] = []
        for attempt in range(1, attempts + 1):
            attempt_started = time.monotonic()
            request = urllib.request.Request(url, data=encoded, headers=self._headers(), method="POST")
            try:
                with self.opener.open(request, timeout=int(self.config.get("timeout_seconds") or 180)) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if isinstance(payload, dict):
                    payload["_transport"] = {
                        "attempts": attempt,
                        "prior_errors": errors,
                        "attempt_elapsed_seconds": round(time.monotonic() - attempt_started, 3),
                        "elapsed_seconds": round(time.monotonic() - request_started, 3),
                    }
                return payload
            except urllib.error.HTTPError as exc:
                detail = exc.read(3000).decode("utf-8", "replace")
                message = "智能LLM请求失败（HTTP {}）：{}".format(exc.code, detail)
                if exc.code not in retryable_statuses:
                    raise RuntimeError(message) from exc
                errors.append(message)
                if attempt >= attempts:
                    raise IntelligenceTransportError(message, attempt, errors) from exc
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, EOFError, json.JSONDecodeError) as exc:
                message = "智能LLM传输失败（{}）：{}".format(type(exc).__name__, exc)
                errors.append(message)
                if attempt >= attempts:
                    raise IntelligenceTransportError(message, attempt, errors) from exc
            if backoff:
                time.sleep(min(30.0, backoff * (2 ** (attempt - 1))))
        raise IntelligenceTransportError("智能LLM传输失败", attempts, errors)

    def _call_json(
        self,
        name: str,
        instruction: str,
        images: Iterable[Path],
        schema: Dict[str, Any],
        reasoning_effort: str = "",
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        content: List[Dict[str, Any]] = [{"type": "input_text", "text": instruction}]
        for path in images:
            content.append({"type": "input_image", "image_url": _image_data_url(path), "detail": "high"})
        body: Dict[str, Any] = {
            "model": str(self.config.get("model") or "gpt-5.6-sol"),
            "input": [{"role": "user", "content": content}],
            "reasoning": {
                "effort": str(reasoning_effort or self.config.get("reasoning_effort") or "medium")
            },
            "text": {"format": {"type": "json_schema", "name": name, "strict": True, "schema": schema}},
            "store": False,
        }
        try:
            response = self._request(body)
        except RuntimeError as exc:
            # Some compatible gateways implement Responses vision but not strict
            # structured output. Retry once with an explicit JSON instruction.
            if "HTTP 400" not in str(exc):
                raise
            body.pop("text", None)
            content[0]["text"] += "\n\n只输出一个符合下述JSON Schema的JSON对象，不要Markdown：\n" + json.dumps(schema, ensure_ascii=False)
            response = self._request(body)
        return _json_from_text(_response_text(response)), response

    @staticmethod
    def _write_audit(path: Path, request_summary: Dict[str, Any], result: Dict[str, Any], response: Dict[str, Any]) -> None:
        usage = response.get("usage", {}) if isinstance(response, dict) else {}
        payload = {
            "request": request_summary,
            "result": result,
            "response": {
                "id": response.get("id", ""), "model": response.get("model", ""), "usage": usage,
                "transport": response.get("_transport", {}),
            },
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def plan(
        self,
        source_path: Path,
        roi_mask_path: Path,
        labels: List[str],
        shapes: List[Dict[str, Any]],
        base_prompt: str,
        references: List[Path],
        attempt_dir: Path,
        focus_mask_path: Optional[Path] = None,
        failed_candidate_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
        context_path = build_roi_context(
            source_path, roi_mask_path, attempt_dir / "intelligence_roi_context.png", focus_mask_path
        )
        reference_count = min(len(references), int(self.config.get("reference_candidate_count") or 5))
        reference_range = "没有同标签参考候选" if reference_count == 0 else "第3至第{}张是同标签参考候选".format(reference_count + 2)
        instruction = """你是工业设备异常数据生成的视觉策略总控，职责接近资深人工数据工程师，不负责直接生图。
图片顺序：1=待编辑干净完整源图；2=同一源图的定位视图（绿色=LabelMe语义重点，橙色=更宽的CORE上下文编辑边界，橙色区外变暗；彩色线仅用于定位且不能出现在结果图）；之后若有图片则是独立参考异常，只能学习异常规律，不能复制设备身份。
{}；selected_reference_indices使用从0开始的候选下标选择最适合当前结构的参考；没有候选时必须返回空数组。不要因为标签一致就盲目选择结构不相似的参考。若最后还有一张标记为“上一轮失败候选”，必须分析它为何失败并改变策略。
请先根据完整源图理解整体机械结构，再结合真实遮挡、连接、光照、当前标签、绿色关注区、橙色上下文编辑区、参考候选和历史审核意见，决定：最合适参考、编辑范围尺度、失败后的策略变化，并为图片编辑CORE写实例级指令。LabelMe框不是异常边界：异常及其直接相关的背景恢复、接触阴影、流淌等可以越过绿色框，但不得越过最终编辑边界或改动无关内容。必须判断目标具体是什么、应增加或移除什么、移除后应露出什么已有背景/孔口/安装面、哪些相邻结构必须保留。不得臆造没有视觉依据的机构。灰度源图必须保持灰度。
以下是知识库和审核意见形成的基础约束：
---
{}
---
当前标签：{}
当前shape：{}
输出JSON。edit_instruction必须可直接追加到生图提示词，内容具体、简洁、无分析过程；strategy_summary说明本轮相较上轮改变了什么。""".format(
            reference_range, base_prompt, json.dumps(labels, ensure_ascii=False), json.dumps(shapes, ensure_ascii=False)
        )
        instruction += """

强制实例推理要求：
1. scene_analysis 必须先说明完整源图中的目标、相邻结构、遮挡、光照和重力方向；不得只描述框内像素。
2. physical_anchor 必须指出异常依附、缺失或泄漏的具体机械锚点；漏油须指出源点和连续流动路径，异物须指出夹持/搭挂/黏附接触点。
3. 每张知识库参考候选均已依据其 LabelMe 标注裁到异常附近。selected_reference_indices 和 reference_rationale 必须依据裁图中心的异常本体选择，禁止学习参考图内其他正常暗色部件。
4. 对 S_HeiJiaoDai：必须是意外遗留、撕裂、折叠或松散搭挂的异物片段。若像整齐均匀的多圈包扎、护套或正常安装件，则策略不合格。
5. 对 LY：必须避免纯黑油漆、规则高光液珠、孤立黑点和矩形灰度块；保留宿主纹理并形成源点—浸润—流痕/积油的物理连续性。
6. background_preservation_plan 必须具体说明如何保持编辑区边缘灰度、噪声、纹理和所有无关结构；negative_patterns_to_avoid 至少列出三项当前最可能失败的形态。
7. edit_instruction 必须把以上实例结论转成 CORE 可直接执行的指令，并要求输出前比较源图，消除矩形边缘和灰度接缝。
8. 你必须真正管理可执行 Mask，而不是只描述“收紧”。优先令 mask_geometry=agent_regions，并在 mask_regions 中用 Image 1 的绝对像素坐标给出实际允许编辑的多个局部岛。每个缺失零件、油迹流动段或异物接触区可以单独给一个 polygon/ellipse/rectangle；points 对 polygon 至少给3点，对 rectangle/ellipse 给对角两点；padding_px 只给物理连续性需要的少量外扩。mask_regions 是实际可编辑区域，不是目标检测框，不得用一个大矩形包住大量无关背景。
9. protected_regions 用同样的绝对像素坐标列出必须硬锁定的孔洞、托板边缘、轴、相邻零件、高光或其他容易被误改的结构；它们会由程序从可编辑 Mask 中扣除。没有必要保护时返回空数组。所有坐标必须位于当前 image_size 内，并与 scene_analysis 中识别的真实结构一致；禁止猜测看不清的细轮廓。只有无法可靠给出局部区域时才使用 focus_dilation/rounded_context并让 mask_regions=[]。
10. candidate_directives 给出至少三种互补但都合规的候选执行侧重点，分别强调物理形态、反事实保真和异常可检测性；不能让候选改变标签语义。
"""
        image_paths = [source_path, context_path] + list(references[:reference_count])
        if failed_candidate_path is not None and failed_candidate_path.is_file():
            instruction += "\n\n最后一张图片是上一轮失败候选，不是正面参考；必须避免重复其中的问题。"
            image_paths.append(failed_candidate_path)
        result, response = self._call_json(
            "anomaly_edit_plan", instruction, image_paths, PLANNER_SCHEMA,
            str(self.config.get("planner_reasoning_effort") or ""),
        )
        self._write_audit(
            attempt_dir / "intelligence_plan.json",
            {"labels": labels, "shapes": shapes, "images": [str(path) for path in image_paths]},
            result, response,
        )
        return result

    def plan_batch(
        self,
        source_path: Path,
        items: List[Dict[str, Any]],
        batch_dir: Path,
    ) -> Dict[str, Dict[str, Any]]:
        """Plan several LabelMe ROIs from the same source in one vision call.

        Scene interpretation and preservation constraints are shared, while
        every ROI still receives an independent executable strategy, reference
        selection, mask geometry and retry action.
        """
        if not items:
            return {}
        batch_dir.mkdir(parents=True, exist_ok=True)
        image_paths: List[Path] = [source_path]
        item_lines: List[str] = []
        request_items: List[Dict[str, Any]] = []
        context_positions: Dict[str, int] = {}

        for item_index, item in enumerate(items):
            roi_id = str(item["roi_id"])
            context_path = build_roi_context(
                Path(item.get("source_path") or source_path),
                Path(item["roi_mask_path"]),
                batch_dir / "roi_{:02d}_context.png".format(item_index + 1),
                Path(item["focus_mask_path"]) if item.get("focus_mask_path") else None,
            )
            image_paths.append(context_path)
            context_positions[roi_id] = len(image_paths)

        for item in items:
            roi_id = str(item["roi_id"])
            references = [Path(path) for path in item.get("references") or []]
            reference_positions: List[int] = []
            for reference in references:
                image_paths.append(reference)
                reference_positions.append(len(image_paths))
            failed_position = 0
            failed_candidate = item.get("failed_candidate_path")
            if failed_candidate:
                image_paths.append(Path(failed_candidate))
                failed_position = len(image_paths)
            reference_text = "无参考候选" if not reference_positions else "局部参考下标0..{}对应图片{}".format(
                len(reference_positions) - 1, reference_positions
            )
            failure_text = "无失败候选" if not failed_position else "上一轮失败拼图=图片{}，只作负例".format(failed_position)
            item_lines.append(
                "ROI_ID={}; 定位视图=图片{}; labels={}; shapes={}; {}; {}\n该ROI知识与审核输入：\n{}".format(
                    roi_id,
                    context_positions[roi_id],
                    json.dumps(item.get("labels") or [], ensure_ascii=False),
                    json.dumps(item.get("shapes") or [], ensure_ascii=False),
                    reference_text,
                    failure_text,
                    str(item.get("base_prompt") or ""),
                )
            )
            request_items.append(
                {
                    "roi_id": roi_id,
                    "labels": item.get("labels") or [],
                    "source": str(item.get("source_path") or source_path),
                    "context_image": context_positions[roi_id],
                    "reference_images": reference_positions,
                    "failed_candidate_image": failed_position,
                }
            )

        instruction = """你是工业设备异常数据生成的视觉策略总控。一次请求中有同一张干净源图的多个LabelMe ROI，请先做一次整图机械结构分析，再分别输出每个ROI的独立生成策略。
图片1=待编辑干净完整源图。每个ROI均有单独定位视图：绿色是LabelMe语义重点，橙色是初始可编辑上下文；彩色线只用于分析，禁止出现在结果中。后续参考图只学习异常规律，禁止复制设备身份。失败候选只用于识别错误，禁止继承其像素或结构。

关键规则：
1. roi_plans必须与下面ROI_ID一一对应，不得遗漏、合并或新增。
2. 多个ROI共享相机、曝光、灰度、机械结构与遮挡关系，但每个ROI的edit_instruction、mask_regions、protected_regions、参考选择和重试策略必须独立。
3. LabelMe框只是语义重点，不是硬编辑边界；异常直接影响、背景恢复、接触阴影或流淌可合理越框，但无关区域必须逐像素保持。
4. selected_reference_indices采用该ROI自己的局部参考下标，不是全局图片编号。
5. 删除类必须描述目标移除后真实暴露的背景、接口、阴影和连接关系；新增类必须描述材质、受力/重力、接触和报警强度。
6. mask_regions必须是实际最大可改区域，protected_regions明确锁定邻近关键结构；禁止把ROI矩形直接当成异常轮廓。
7. shared_preservation_constraints应列出所有ROI都必须遵守的整图保持条件；每个roi_plan仍需给出完整可独立执行的字段。

ROI任务清单：
{}

只返回严格符合Schema的JSON。""".format("\n\n".join(item_lines))
        result, response = self._call_json(
            "anomaly_edit_batch_plan", instruction, image_paths, BATCH_PLANNER_SCHEMA,
            str(self.config.get("planner_reasoning_effort") or ""),
        )
        returned = result.get("roi_plans") or []
        plans: Dict[str, Dict[str, Any]] = {}
        for value in returned:
            if not isinstance(value, dict):
                continue
            roi_id = str(value.get("roi_id") or "")
            if roi_id and roi_id not in plans:
                plan = dict(value)
                plan.pop("roi_id", None)
                plan["shared_scene_analysis"] = str(result.get("shared_scene_analysis") or "")
                plan["shared_preservation_constraints"] = list(result.get("shared_preservation_constraints") or [])
                plan["batch_planned"] = True
                plans[roi_id] = plan
        expected = {str(item["roi_id"]) for item in items}
        if set(plans) != expected:
            missing = sorted(expected.difference(plans))
            extra = sorted(set(plans).difference(expected))
            raise ValueError("批量规划ROI不匹配；缺少={}，多出={}".format(missing, extra))
        self._write_audit(
            batch_dir / "intelligence_batch_plan.json",
            {"source": str(source_path), "images": [str(path) for path in image_paths], "items": request_items},
            result,
            response,
        )
        return plans

    def compare_candidates(
        self,
        source_path: Path,
        roi_context_path: Path,
        candidate_paths: List[Path],
        labels: List[str],
        plan: Dict[str, Any],
        candidate_reports: List[Dict[str, Any]],
        attempt_dir: Path,
        references: Iterable[Path] = (),
    ) -> Dict[str, Any]:
        if not candidate_paths:
            raise ValueError("没有可比较候选")
        instruction = """你是工业异常生成代理的候选择优总控，而不是逐图孤立打分员。
图片顺序：1=本轮实际编辑基础图（可能已经含有必须锁定的前序ROI异常）；2=LabelMe/编辑范围定位视图；随后依次是候选1至候选N；最后如有则是本轮异常参考裁图。

你的任务是横向比较所有候选，选择最接近资深人工数据工程师结果的一张。必须同时权衡：
1. 标签语义和报警可见性；
2. 真实机械结构、材料、遮挡、接触、重力和泄漏路径；
3. 反事实一致性：移除异常后能恢复基础图；
4. 编辑范围外及异常直接影响外的灰度、纹理、噪声和结构保持；
5. 不出现矩形贴片、灰度接缝、无依据结构、正常安装件效果。

不能因为所有候选都差就强行通过。selected_index 使用从0开始的候选下标；即使全部失败，也选择最有修复价值的一张并给出下一轮 revision_instruction 和 next_strategy。candidate_scores 中必须覆盖每个候选，score为0至100整数。

当前标签：{}
生成计划：{}
程序预检查与逐候选语义报告：{}
""".format(
            json.dumps(labels, ensure_ascii=False), json.dumps(plan, ensure_ascii=False),
            json.dumps(candidate_reports, ensure_ascii=False),
        )
        reference_paths = list(references)
        images = [source_path, roi_context_path] + list(candidate_paths) + reference_paths
        result, response = self._call_json(
            "anomaly_candidate_comparison", instruction, images, COMPARISON_SCHEMA,
            str(self.config.get("comparison_reasoning_effort") or ""),
        )
        self._write_audit(
            attempt_dir / "intelligence_comparison.json",
            {
                "labels": labels, "images": [str(path) for path in images], "plan": plan,
                "candidate_reports": candidate_reports, "candidate_count": len(candidate_paths),
            },
            result, response,
        )
        return result

    def critique(
        self,
        source_path: Path,
        candidate_path: Path,
        roi_context_path: Path,
        labels: List[str],
        plan: Dict[str, Any],
        attempt_dir: Path,
        references: Iterable[Path] = (),
    ) -> Dict[str, Any]:
        instruction = """你是工业异常反事实编辑的严格质检员。
图片顺序：1=干净源图；2=生成候选；3=定位视图（绿色=LabelMe重点，橙色=CORE编辑上下文）；之后是本轮实际使用的异常参考图。参考图只用于判断异常语义和物理形态，不能要求复制其设备。
检查：异常语义是否符合标签；异常是否足够清楚；机械结构是否合理；目标是否完整增加/移除；除异常直接影响外是否保持源图；是否有色偏、硬边、纹理重绘、悬空结构或无依据的新结构。
允许图片区分造成的正常压缩/轻微噪声差异，但不得放过明显语义错误。minor且不影响训练可用性时可以pass=true；major必须pass=false。
当前标签：{}
生成前计划：{}
输出JSON。reason_codes只能使用Schema给出的值；若不通过，revision_instruction必须能直接指导下一轮从干净源图重做。""".format(
            json.dumps(labels, ensure_ascii=False), json.dumps(plan, ensure_ascii=False)
        )
        instruction += """

额外硬性检查：
- 沿编辑上下文边界检查是否存在矩形灰度块、曝光跳变、模糊边、噪声/锐度突变；存在时 background_seam_detected=true，使用 BACKGROUND_CHANGED 或 EDGE_ARTIFACT，且不得通过。
- 若标签为 S_HeiJiaoDai，而结果像整齐包扎、正常护套或安装件，looks_like_normal_installation=true，使用 WRONG_LABEL 或 WRONG_STRUCTURE，且不得通过。
- 对照干净源图逐项判断：移除新增异常后能否恢复原图结构、纹理和灰度，并写入 counterfactual_consistency。
"""
        reference_limit = max(0, int(self.config.get("critic_reference_count") or 1))
        image_paths = [source_path, candidate_path, roi_context_path] + list(references)[:reference_limit]
        result, response = self._call_json(
            "anomaly_semantic_review", instruction, image_paths, CRITIC_SCHEMA,
            str(self.config.get("critic_reasoning_effort") or ""),
        )
        self._write_audit(
            attempt_dir / "intelligence_critic.json",
            {"labels": labels, "images": [str(path) for path in image_paths], "plan": plan},
            result, response,
        )
        return result

    def probe(self) -> Dict[str, Any]:
        body = {
            "model": str(self.config.get("model") or "gpt-5.6-sol"),
            "input": "Return exactly: INTELLIGENCE_OK",
            "reasoning": {"effort": "low"},
            "store": False,
        }
        response = self._request(body)
        output = _response_text(response).strip()
        return {
            "endpoint": self._url(), "model": body["model"], "response_id": response.get("id", ""),
            "ok": "INTELLIGENCE_OK" in output, "output": output[:200], "usage": response.get("usage", {}),
        }


def create_intelligence(config: Dict[str, Any]) -> Optional[VisionLLMClient]:
    if not bool(config.get("intelligence", {}).get("enabled", False)):
        return None
    return VisionLLMClient(config)


def probe_intelligence(config: Dict[str, Any]) -> Dict[str, Any]:
    client = VisionLLMClient(config)
    return client.probe()
