"""Evaluate saved model outputs against pixels/masks and optional human verdicts.

This does not generate images and cannot prove physical realism automatically.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageChops


def binary(image):
    return image.convert("L").point(lambda v: 255 if v >= 128 else 0)


def count(image):
    return image.histogram()[255]


def resolve(root, value):
    path = Path(value)
    return path if path.is_absolute() else root / path


def evaluate_case(case, root):
    paths = {key: resolve(root, case[key]) for key in ("source", "candidate", "allowed_mask", "mask")}
    images = {}
    for key, path in paths.items():
        with Image.open(path) as image:
            images[key] = image.copy()
    source, candidate = images["source"].convert("RGB"), images["candidate"].convert("RGB")
    failures = []
    metrics = {}
    if any(image.size != source.size for image in images.values()):
        failures.append("SIZE_MISMATCH")
    else:
        # Max RGB delta prevents chromatic changes being hidden by grayscale conversion.
        channels = ImageChops.difference(source, candidate).split()
        delta = ImageChops.lighter(channels[0], ImageChops.lighter(channels[1], channels[2]))
        changed = delta.point(lambda v: 255 if v > 0 else 0)
        allowed, mask = binary(images["allowed_mask"]), binary(images["mask"])
        outside = ImageChops.multiply(changed, ImageChops.invert(allowed))
        pixels = source.width * source.height
        metrics.update(changed_pixels=count(changed), changed_fraction=count(changed) / pixels,
                       outside_changed_pixels=count(outside), mask_pixels=count(mask),
                       mask_outside_pixels=count(ImageChops.multiply(mask, ImageChops.invert(allowed))))
        if metrics["changed_pixels"] == 0:
            failures.append("EMPTY_CHANGE")
        if metrics["outside_changed_pixels"] > int(case.get("max_outside_changed_pixels", 0)):
            failures.append("BACKGROUND_CHANGED")
        if metrics["mask_outside_pixels"]:
            failures.append("MASK_OUTSIDE_ALLOWED")
        if not metrics["mask_pixels"]:
            failures.append("EMPTY_MASK")
        if metrics["changed_fraction"] < float(case.get("min_changed_fraction", 0)):
            failures.append("CHANGE_BELOW_CASE_THRESHOLD")
        r, g, b = source.split()
        source_gray = ImageChops.difference(r, g).getbbox() is None and ImageChops.difference(r, b).getbbox() is None
        r, g, b = candidate.split()
        candidate_gray = ImageChops.difference(r, g).getbbox() is None and ImageChops.difference(r, b).getbbox() is None
        metrics["grayscale_preserved"] = not source_gray or candidate_gray
        if not metrics["grayscale_preserved"]:
            failures.append("COLOR_SHIFT")
        bbox = changed.getbbox()
        margin = int(case.get("border_margin_px", 1))
        if bbox and (bbox[0] < margin or bbox[1] < margin or bbox[2] > source.width - margin or bbox[3] > source.height - margin):
            failures.append("CHANGE_NEAR_BORDER")
        if case.get("gold_mask"):
            with Image.open(resolve(root, case["gold_mask"])) as gold_image:
                gold = binary(gold_image)
            if gold.size != source.size:
                failures.append("GOLD_MASK_SIZE_MISMATCH")
            else:
                intersection = count(ImageChops.multiply(gold, mask))
                union = count(ImageChops.lighter(gold, mask))
                metrics["mask_iou"] = intersection / union if union else 1.0
                if metrics["mask_iou"] < float(case.get("min_mask_iou", 0.8)):
                    failures.append("MASK_IOU_LOW")
    human_pass = case.get("human_pass")
    if human_pass is not None and type(human_pass) is not bool:
        raise ValueError("human_pass must be true, false or null")
    model_pass = case.get("model_pass")
    if model_pass is not None and type(model_pass) is not bool:
        raise ValueError("model_pass must be true, false or null")
    return {"id": case["id"], "label": case.get("label", ""), "failures": failures, "metrics": metrics,
            "automatic_pass": not failures, "human_pass": human_pass, "model_pass": model_pass,
            "verdict": "failed" if failures or human_pass is False else ("passed" if human_pass is True else "manual_pending"),
            "sha256": {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in paths.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
    cases = manifest.get("cases", [])
    if not cases:
        parser.error("cases must not be empty")
    ids = [c["id"] for c in cases]
    if len(ids) != len(set(ids)):
        parser.error("case IDs must be unique")
    results = []
    for case in cases:
        try:
            results.append(evaluate_case(case, args.manifest.resolve().parent))
        except (ValueError, OSError, KeyError) as exc:
            results.append({"id": case.get("id", ""), "verdict": "error", "error": str(exc)})
    compared = [r for r in results if type(r.get("model_pass")) is bool and type(r.get("human_pass")) is bool]
    summary = {"total": len(results), "passed": sum(r["verdict"] == "passed" for r in results),
               "manual_pending": sum(r["verdict"] == "manual_pending" for r in results),
               "failed": sum(r["verdict"] in {"failed", "error"} for r in results),
               "critic_compared": len(compared),
               "critic_false_accepts": sum(r["model_pass"] and not r["human_pass"] for r in compared),
               "critic_false_rejects": sum(not r["model_pass"] and r["human_pass"] for r in compared)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"summary": summary, "results": results}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    # Pending human review is not a successful real-quality validation.
    return 1 if summary["failed"] else (2 if summary["manual_pending"] else 0)


if __name__ == "__main__":
    raise SystemExit(main())
