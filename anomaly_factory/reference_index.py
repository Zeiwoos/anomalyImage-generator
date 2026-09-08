from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, DefaultDict, Dict, List


def build_reference_index(reference_root: Path, output_path: Path) -> Dict[str, Any]:
    reference_root = reference_root.resolve()
    labels: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
    errors: List[str] = []
    image_count = 0
    fault_image_count = 0
    normal_image_count = 0
    aliases: Dict[str, str] = {}
    labels_path = output_path.parent / "labels.json"
    if labels_path.is_file():
        try:
            aliases = json.loads(labels_path.read_text(encoding="utf-8")).get("aliases", {})
        except (OSError, ValueError, json.JSONDecodeError):
            aliases = {}
    parsed_rows: List[Dict[str, Any]] = []
    for json_path in sorted(reference_root.rglob("*.json")):
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8-sig"))
            image_value = str(payload.get("imagePath") or "").strip()
            image_path = (json_path.parent / image_value).resolve() if image_value else json_path.with_suffix(".jpg").resolve()
            if not image_path.is_file():
                raise FileNotFoundError(image_path)
            image_count += 1
            stem = json_path.stem.lower()
            role = "normal" if stem.endswith("_normal") else "fault"
            if role == "normal":
                normal_image_count += 1
            else:
                fault_image_count += 1
            seen = set()
            for shape in payload.get("shapes") or []:
                label = str(shape.get("label") or "").strip()
                label = str(aliases.get(label, label))
                if not label or label in seen:
                    continue
                seen.add(label)
                parsed_rows.append(
                    {
                        "label": label, "role": role,
                        "image": image_path.relative_to(reference_root).as_posix(),
                        "json": json_path.relative_to(reference_root).as_posix(),
                        "leaf": json_path.parent.relative_to(reference_root).as_posix(),
                        "folder": json_path.parent.parent.relative_to(reference_root).as_posix() if json_path.parent != reference_root else ".",
                        "shape_count": sum(
                            1 for row in payload.get("shapes") or []
                            if str(aliases.get(str(row.get("label") or "").strip(), str(row.get("label") or "").strip())) == label
                        ),
                    }
                )
        except Exception as exc:
            errors.append("{}: {}".format(json_path.relative_to(reference_root), exc))
    normal_lookup: DefaultDict[tuple, List[Dict[str, Any]]] = defaultdict(list)
    for row in parsed_rows:
        if row["role"] == "normal":
            normal_lookup[(row["leaf"], row["label"])].append(row)
    for row in parsed_rows:
        if row["role"] != "fault":
            continue
        item = {key: value for key, value in row.items() if key != "label"}
        item["matching_normals"] = [
            {"image": match["image"], "json": match["json"], "shape_count": match["shape_count"]}
            for match in normal_lookup.get((row["leaf"], row["label"]), [])
        ]
        labels[row["label"]].append(item)
    result = {
        "schema_version": 2,
        "source": "Anomaly-reference",
        "image_count": image_count,
        "fault_image_count": fault_image_count,
        "normal_image_count": normal_image_count,
        "json_count": len(list(reference_root.rglob("*.json"))),
        "labels": {key: value for key, value in sorted(labels.items())},
        "errors": errors,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
