from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from .config import load_claude_environment, load_config, project_paths
from .pipeline import Pipeline
from .core import probe_core
from .intelligence import probe_intelligence
from .reference_index import build_reference_index
from .review_server import serve


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="工业异常图像生成人工闭环")
    value.add_argument("--config", default=str(Path(__file__).resolve().parent.parent / "config.json"))
    sub = value.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="检查项目配置、知识库和CORE凭据状态")
    sub.add_parser("probe-core", help="联网验证图像网关、模型和Image Edits协议，不生成图片")
    sub.add_parser("probe-intelligence", help="发送一次极小文本请求，验证视觉LLM规划接口；不生成图片")
    sub.add_parser("index-references", help="重建学习库2参考索引")
    sub.add_parser("scan", help="扫描待处理LabelMe数据集")
    generate = sub.add_parser("generate", help="调用CORE生成候选")
    generate.add_argument("--queued-only", action="store_true", help="只处理审核驳回的重生成队列")
    generate.add_argument("--sample-id", action="append", default=[], help="只生成指定sample_id，可重复")
    review = sub.add_parser("review", help="启动异常图+Mask一体化审核台")
    review.add_argument("--no-browser", action="store_true")
    export = sub.add_parser("export-approved", help="导出全部已通过样本")
    export.add_argument("--output", default="")
    sub.add_parser("export-results", help="仅刷新审核意见CSV")
    return value


def doctor(config) -> dict:
    paths = project_paths(config)
    runtime = load_claude_environment(config)
    core = config["core"]
    base_key = str(core.get("base_url_env") or "")
    api_key = str(core.get("api_key_env") or "")
    intelligence = config.get("intelligence", {})
    labels_path = paths["knowledge"] / "labels.json"
    index_path = paths["knowledge"] / "reference_index.json"
    dataset_value = str(config["dataset"].get("root") or "").strip()
    return {
        "project_root": str(paths["root"]),
        "reference_root": {"path": str(paths["reference"]), "exists": paths["reference"].is_dir()},
        "knowledge": {"labels": labels_path.is_file(), "reference_index": index_path.is_file()},
        "intermediate_root": str(paths["intermediate"]),
        "dataset_configured": bool(dataset_value),
        "core": {
            "adapter": core.get("adapter"), "model": core.get("model") or runtime.get("ANTHROPIC_MODEL", ""),
            "base_url_configured": bool(core.get("base_url") or runtime.get(base_key)),
            "api_key_configured": bool(runtime.get(api_key)), "endpoint": core.get("endpoint"),
            "proxy_mode": core.get("proxy_mode", "auto"),
        },
        "intelligence": {
            "enabled": bool(intelligence.get("enabled", False)),
            "model": intelligence.get("model", ""), "endpoint": intelligence.get("endpoint", "/v1/responses"),
            "planner": bool(intelligence.get("planner", True)), "critic": bool(intelligence.get("critic", True)),
            "critic_gate": bool(intelligence.get("critic_gate", True)),
            "credentials_shared_with_core": bool(runtime.get(api_key)),
        },
    }


def main(argv: Optional[List[str]] = None) -> int:
    args = parser().parse_args(argv)
    try:
        config = load_config(Path(args.config))
        paths = project_paths(config)
        if args.command == "doctor":
            print(json.dumps(doctor(config), ensure_ascii=False, indent=2))
            return 0
        if args.command == "probe-core":
            result = probe_core(config)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result.get("selected_model_available") and result.get("image_edits_recognized") else 2
        if args.command == "probe-intelligence":
            result = probe_intelligence(config)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result.get("ok") else 2
        if args.command == "index-references":
            result = build_reference_index(paths["reference"], paths["knowledge"] / "reference_index.json")
            print(json.dumps({"images": result["image_count"], "labels": len(result["labels"]), "errors": result["errors"]}, ensure_ascii=False, indent=2))
            return 0 if not result["errors"] else 2
        pipeline = Pipeline(config)
        if args.command == "scan":
            print(json.dumps(pipeline.scan(), ensure_ascii=False, indent=2))
        elif args.command == "generate":
            print(json.dumps(pipeline.generate(args.queued_only, args.sample_id or None), ensure_ascii=False, indent=2))
        elif args.command == "review":
            serve(pipeline, args.no_browser)
        elif args.command == "export-approved":
            output = Path(args.output) if args.output else None
            print(json.dumps(pipeline.export_approved(output), ensure_ascii=False, indent=2))
        elif args.command == "export-results":
            print(pipeline.export_results_csv())
        return 0
    except Exception as exc:
        print("ERROR: {}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
