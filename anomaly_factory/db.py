from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS samples (
    id TEXT PRIMARY KEY,
    relative_json TEXT NOT NULL,
    json_path TEXT NOT NULL,
    image_path TEXT NOT NULL,
    sample_dir TEXT NOT NULL,
    split TEXT NOT NULL DEFAULT 'anomaly',
    source_mode TEXT NOT NULL DEFAULT 'labelme',
    labels_json TEXT NOT NULL,
    shapes_json TEXT NOT NULL,
    warnings_json TEXT NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    workflow TEXT NOT NULL DEFAULT 'pending_generation',
    active_attempt INTEGER NOT NULL DEFAULT 0,
    anomaly_status TEXT NOT NULL DEFAULT 'pending',
    anomaly_reason_codes TEXT NOT NULL DEFAULT '[]',
    anomaly_comment TEXT NOT NULL DEFAULT '',
    mask_status TEXT NOT NULL DEFAULT 'pending',
    mask_reason_codes TEXT NOT NULL DEFAULT '[]',
    mask_comment TEXT NOT NULL DEFAULT '',
    deleted INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attempts (
    sample_id TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    prompt_path TEXT NOT NULL,
    roi_mask_path TEXT NOT NULL,
    raw_output_path TEXT NOT NULL,
    candidate_path TEXT NOT NULL,
    mask_path TEXT NOT NULL,
    references_json TEXT NOT NULL,
    qc_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(sample_id, attempt),
    FOREIGN KEY(sample_id) REFERENCES samples(id)
);
CREATE TABLE IF NOT EXISTS review_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sample_id TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    reason_codes TEXT NOT NULL,
    comment TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scan_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(samples)").fetchall()}
            if "split" not in columns:
                conn.execute("ALTER TABLE samples ADD COLUMN split TEXT NOT NULL DEFAULT 'anomaly'")
            if "source_mode" not in columns:
                conn.execute("ALTER TABLE samples ADD COLUMN source_mode TEXT NOT NULL DEFAULT 'labelme'")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.path), timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def record_scan_errors(self, errors: Iterable[str]) -> None:
        stamp = now_iso()
        with self.connect() as conn:
            conn.execute("DELETE FROM scan_errors")
            conn.executemany("INSERT INTO scan_errors(message, created_at) VALUES (?, ?)", [(e, stamp) for e in errors])

    def upsert_sample(self, row: Dict[str, Any]) -> None:
        stamp = now_iso()
        with self.connect() as conn:
            existing = conn.execute("SELECT labels_json, shapes_json, image_path, split, source_mode FROM samples WHERE id=?", (row["id"],)).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO samples(
                        id, relative_json, json_path, image_path, sample_dir, split, source_mode,
                        labels_json, shapes_json, warnings_json, width, height, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["id"], row["relative_json"], row["json_path"], row["image_path"], row["sample_dir"],
                        row.get("split", "anomaly"), row.get("source_mode", "labelme"),
                        row["labels_json"], row["shapes_json"], row["warnings_json"], row["width"], row["height"], stamp,
                    ),
                )
            else:
                changed = (
                    existing["labels_json"] != row["labels_json"]
                    or existing["shapes_json"] != row["shapes_json"]
                    or existing["image_path"] != row["image_path"]
                    or existing["split"] != row.get("split", "anomaly")
                    or existing["source_mode"] != row.get("source_mode", "labelme")
                )
                conn.execute(
                    """
                    UPDATE samples SET relative_json=?, json_path=?, image_path=?, sample_dir=?, split=?, source_mode=?,
                        labels_json=?, shapes_json=?, warnings_json=?, width=?, height=?,
                        workflow=CASE WHEN ? THEN 'pending_generation' ELSE workflow END,
                        anomaly_status=CASE WHEN ? THEN 'pending' ELSE anomaly_status END,
                        mask_status=CASE WHEN ? THEN 'pending' ELSE mask_status END,
                        updated_at=? WHERE id=?
                    """,
                    (
                        row["relative_json"], row["json_path"], row["image_path"], row["sample_dir"],
                        row.get("split", "anomaly"), row.get("source_mode", "labelme"),
                        row["labels_json"], row["shapes_json"], row["warnings_json"], row["width"], row["height"],
                        int(changed), int(changed), int(changed), stamp, row["id"],
                    ),
                )

    @staticmethod
    def _decode(row: sqlite3.Row) -> Dict[str, Any]:
        value = dict(row)
        for key in ("labels_json", "shapes_json", "warnings_json", "anomaly_reason_codes", "mask_reason_codes", "references_json", "qc_json"):
            if key in value:
                try:
                    value[key.removesuffix("_json") if key.endswith("_json") else key] = json.loads(value[key])
                except (TypeError, json.JSONDecodeError):
                    value[key.removesuffix("_json") if key.endswith("_json") else key] = [] if "codes" in key or "labels" in key or "shapes" in key or "warnings" in key else {}
        value["deleted"] = bool(value.get("deleted", 0))
        return value

    def get_sample(self, sample_id: str) -> Dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM samples WHERE id=?", (sample_id,)).fetchone()
        if row is None:
            raise KeyError("样本不存在：{}".format(sample_id))
        return self._decode(row)

    def list_samples(self, include_deleted: bool = False) -> List[Dict[str, Any]]:
        query = "SELECT * FROM samples"
        if not include_deleted:
            query += " WHERE deleted=0"
        query += " ORDER BY relative_json COLLATE NOCASE"
        with self.connect() as conn:
            rows = conn.execute(query).fetchall()
        return [self._decode(row) for row in rows]

    def next_attempt(self, sample_id: str) -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT COALESCE(MAX(attempt), 0) AS n FROM attempts WHERE sample_id=?", (sample_id,)).fetchone()
        return int(row["n"]) + 1

    def add_attempt(self, row: Dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO attempts(sample_id, attempt, prompt_path, roi_mask_path, raw_output_path,
                    candidate_path, mask_path, references_json, qc_json, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["sample_id"], row["attempt"], row["prompt_path"], row["roi_mask_path"], row["raw_output_path"],
                    row["candidate_path"], row["mask_path"], json.dumps(row.get("references", []), ensure_ascii=False),
                    json.dumps(row.get("qc", {}), ensure_ascii=False), row["status"], now_iso(),
                ),
            )
            conn.execute(
                """
                UPDATE samples SET active_attempt=?, workflow=?, anomaly_status='pending',
                    mask_status='pending', updated_at=? WHERE id=?
                """,
                (row["attempt"], row["workflow"], now_iso(), row["sample_id"]),
            )

    def active_attempt(self, sample_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                """SELECT a.* FROM attempts a JOIN samples s ON s.id=a.sample_id
                   WHERE a.sample_id=? AND a.attempt=s.active_attempt""",
                (sample_id,),
            ).fetchone()
        return self._decode(row) if row is not None else None

    def attempts_for_sample(self, sample_id: str, limit: int = 0, descending: bool = True) -> List[Dict[str, Any]]:
        query = "SELECT * FROM attempts WHERE sample_id=? ORDER BY attempt {}".format("DESC" if descending else "ASC")
        parameters: List[Any] = [sample_id]
        if limit > 0:
            query += " LIMIT ?"
            parameters.append(int(limit))
        with self.connect() as conn:
            rows = conn.execute(query, parameters).fetchall()
        return [self._decode(row) for row in rows]

    def invalidate_dependents(self, changed_sample_id: str) -> List[str]:
        """Queue active candidates that were generated on top of the changed ROI."""
        invalidated: List[str] = []
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT s.id, a.qc_json FROM samples s
                   JOIN attempts a ON a.sample_id=s.id AND a.attempt=s.active_attempt
                   WHERE s.deleted=0 AND s.id<>?""",
                (changed_sample_id,),
            ).fetchall()
            for raw in rows:
                try:
                    qc = json.loads(str(raw["qc_json"] or "{}"))
                except (TypeError, json.JSONDecodeError):
                    continue
                dependencies = ((qc.get("agent") or {}).get("base_dependencies") or []) if isinstance(qc, dict) else []
                if changed_sample_id not in dependencies:
                    continue
                conn.execute(
                    """UPDATE samples SET workflow='regen_queued', anomaly_status='rejected',
                       anomaly_reason_codes=?, anomaly_comment=?, updated_at=? WHERE id=?""",
                    (
                        json.dumps(["BACKGROUND_CHANGED"], ensure_ascii=False),
                        "前序ROI已改变；当前候选依赖旧版累积底图，必须按新的前序异常重新生成。",
                        now_iso(), str(raw["id"]),
                    ),
                )
                invalidated.append(str(raw["id"]))
        return invalidated

    def set_workflow(self, sample_id: str, workflow: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE samples SET workflow=?, updated_at=? WHERE id=?", (workflow, now_iso(), sample_id))

    def save_generation_feedback(self, sample_id: str, reason_codes: List[str], comment: str) -> Dict[str, Any]:
        sample = self.get_sample(sample_id)
        allowed_workflows = {"pending_generation", "regen_queued", "qc_failed", "core_not_configured"}
        if sample["workflow"] not in allowed_workflows:
            raise ValueError("只有待生成或待重生成ROI可以保存下一轮生成要求")
        comment = comment.strip()[:5000]
        codes_json = json.dumps(sorted(set(reason_codes)), ensure_ascii=False)
        workflow = "hold" if "ROI_MISALIGNED" in reason_codes else sample["workflow"]
        stamp = now_iso()
        with self.connect() as conn:
            conn.execute(
                "UPDATE samples SET anomaly_reason_codes=?, anomaly_comment=?, workflow=?, updated_at=? WHERE id=?",
                (codes_json, comment, workflow, stamp, sample_id),
            )
            conn.execute(
                "INSERT INTO review_events(sample_id, attempt, stage, status, reason_codes, comment, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (sample_id, int(sample.get("active_attempt") or 0), "anomaly", "feedback_updated", codes_json, comment, stamp),
            )
        return self.get_sample(sample_id)

    def review(self, sample_id: str, stage: str, status: str, reason_codes: List[str], comment: str) -> Dict[str, Any]:
        if stage not in {"anomaly", "mask", "normal"}:
            raise ValueError("invalid review stage")
        if status not in {"pending", "approved", "rejected", "hold"}:
            raise ValueError("invalid review status")
        sample = self.get_sample(sample_id)
        attempt = int(sample["active_attempt"])
        if attempt <= 0:
            raise ValueError("样本尚无生成版本")
        comment = comment.strip()[:5000]
        codes_json = json.dumps(sorted(set(reason_codes)), ensure_ascii=False)
        if stage == "normal":
            workflow = "completed" if status == "approved" else ("normal_review" if status == "pending" else "hold")
            sql = "UPDATE samples SET anomaly_status=?, anomaly_reason_codes=?, anomaly_comment=?, workflow=?, updated_at=? WHERE id=?"
        elif stage == "anomaly":
            if status == "approved":
                workflow = "mask_review"
            elif status == "rejected":
                workflow = "hold" if "ROI_MISALIGNED" in reason_codes or sample.get("source_mode") != "labelme" else "regen_queued"
            elif status == "hold":
                workflow = "hold"
            else:
                workflow = "anomaly_review"
            sql = "UPDATE samples SET anomaly_status=?, anomaly_reason_codes=?, anomaly_comment=?, workflow=?, updated_at=? WHERE id=?"
        else:
            workflow = "completed" if status == "approved" else ("hold" if status == "hold" else "mask_review")
            sql = "UPDATE samples SET mask_status=?, mask_reason_codes=?, mask_comment=?, workflow=?, updated_at=? WHERE id=?"
        with self.connect() as conn:
            conn.execute(sql, (status, codes_json, comment, workflow, now_iso(), sample_id))
            conn.execute(
                "INSERT INTO review_events(sample_id, attempt, stage, status, reason_codes, comment, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (sample_id, attempt, stage, status, codes_json, comment, now_iso()),
            )
        if stage == "anomaly" and status == "rejected":
            self.invalidate_dependents(sample_id)
        return self.get_sample(sample_id)

    def save_mask_path(self, sample_id: str, attempt: int, path: Path) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE attempts SET mask_path=? WHERE sample_id=? AND attempt=?", (str(path.resolve()), sample_id, attempt))
            conn.execute("UPDATE samples SET mask_status='pending', workflow='mask_review', updated_at=? WHERE id=?", (now_iso(), sample_id))

    def refresh_imported_attempt_paths(self, sample_id: str, attempt: int, candidate: Path, mask: Path) -> None:
        """Refresh read-only manifest inputs without resetting review decisions."""
        with self.connect() as conn:
            conn.execute(
                "UPDATE attempts SET raw_output_path=?, candidate_path=?, roi_mask_path=?, mask_path=? WHERE sample_id=? AND attempt=?",
                (str(candidate.resolve()), str(candidate.resolve()), str(mask.resolve()), str(mask.resolve()), sample_id, attempt),
            )

    def mark_deleted(self, sample_id: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE samples SET deleted=1, workflow='deleted', updated_at=? WHERE id=?", (now_iso(), sample_id))

    def mark_deleted_directory(self, sample_dir: Path) -> int:
        target = str(sample_dir.resolve())
        with self.connect() as conn:
            cursor = conn.execute(
                "UPDATE samples SET deleted=1, workflow='deleted', updated_at=? WHERE sample_dir=?",
                (now_iso(), target),
            )
        return int(cursor.rowcount)

    def counts(self) -> Dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute("SELECT workflow, COUNT(*) AS n FROM samples WHERE deleted=0 GROUP BY workflow").fetchall()
        return {str(row["workflow"]): int(row["n"]) for row in rows}
