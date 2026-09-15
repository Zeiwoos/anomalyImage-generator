from __future__ import annotations

import base64
import io
import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from PIL import Image, ImageDraw

from anomaly_factory.config import load_config
from anomaly_factory.pipeline import Pipeline
from anomaly_factory.reference_index import build_reference_index
from anomaly_factory.review_server import Handler, ReviewApplication

PROJECT = Path(__file__).resolve().parents[2]


def write_sample(folder, stem="source", labels=("DS_LS", "LY")):
    """Synthetic geometry, never a real industrial quality reference."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    source = folder / (stem + ".png")
    Image.new("L", (128, 96), 120).save(source)
    shapes = [{"label": label, "shape_type": "rectangle", "group_id": None,
               "points": [[12 + i * 44, 24], [32 + i * 44, 48]], "flags": {}}
              for i, label in enumerate(labels)]
    annotation = folder / (stem + ".json")
    annotation.write_text(json.dumps({
        "imagePath": source.name, "imageWidth": 128, "imageHeight": 96,
        "imageData": None, "shapes": shapes,
    }), encoding="utf-8")
    return annotation


def synthetic_references(folder, count=1):
    write_sample(Path(folder) / "pair", "00_fault")
    write_sample(Path(folder) / "pair", "01_normal")
    fault = Path(folder) / "pair" / "00_fault.png"
    with Image.open(fault) as opened:
        image = opened.copy()
    ImageDraw.Draw(image).rectangle((16, 28, 28, 42), fill=55)
    image.save(fault)
    for index in range(1, count):
        write_sample(Path(folder) / ("pair_" + str(index)), "00_fault")
    return Path(folder)


def png_url(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


class IsolatedPipelineTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get("ANOMALY_TEST_TMPDIR"))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.dataset = self.root / "dataset"
        self.annotation = write_sample(self.dataset / "part_a")
        self.references = synthetic_references(self.root / "reference")
        self.bank = self.root / "knowledge-bank"
        shutil.copytree(PROJECT / "knowledge-bank", self.bank)
        build_reference_index(self.references, self.bank / "reference_index.json")
        self.config_path = self.root / "config.json"
        self.config_path.write_text(json.dumps({
            "project": {"reference_root": str(self.references), "knowledge_root": str(self.bank),
                        "intermediate_root": str(self.root / "work"),
                        "database": str(self.root / "work" / "db.sqlite3")},
            "dataset": {"root": str(self.dataset)},
            "core": {"adapter": "mock", "claude_settings": ""},
            "intelligence": {"enabled": False},
            "generation": {"multi_label_mode": "per_image_layered",
                           "edit_context_min_padding_px": 4, "edit_context_padding_ratio": 0.05,
                           "auto_retry_failed": False},
            "review": {"open_browser": False},
        }), encoding="utf-8")
        # Guard unexpected upstream calls; loopback HTTP tests use an unpatched socket path.
        self.network_guard = patch("urllib.request.OpenerDirector.open",
                                   side_effect=AssertionError("Unexpected external API call in offline test"))
        self.network_guard.start()
        self.addCleanup(self.network_guard.stop)
        self.pipeline = Pipeline(load_config(self.config_path))
        self.pipeline.scan()
        self.app = ReviewApplication(self.pipeline)
        self.rows = sorted(self.pipeline.db.list_samples(), key=lambda row: row["shapes"][0]["index"])

    def seed_attempts(self):
        """Insert synthetic candidates to test review, not model quality."""
        for index, row in enumerate(self.rows):
            attempt = self.pipeline.db.next_attempt(row["id"])
            folder = self.root / "seed" / row["id"] / str(attempt)
            folder.mkdir(parents=True)
            with Image.open(row["image_path"]) as opened:
                candidate = opened.copy()
            box = (16 + index * 44, 28, 28 + index * 44, 42)
            ImageDraw.Draw(candidate).rectangle(box, fill=45)
            mask = Image.new("L", candidate.size, 0)
            ImageDraw.Draw(mask).rectangle(box, fill=255)
            candidate_path, mask_path = folder / "candidate.png", folder / "mask.png"
            candidate.save(candidate_path)
            mask.save(mask_path)
            (folder / "prompt.txt").write_text("Synthetic fixture only", encoding="utf-8")
            self.pipeline.db.add_attempt({
                "sample_id": row["id"], "attempt": attempt, "prompt_path": str(folder / "prompt.txt"),
                "roi_mask_path": str(mask_path), "raw_output_path": str(candidate_path),
                "candidate_path": str(candidate_path), "mask_path": str(mask_path),
                "references": [], "qc": {"passed": True, "failures": []},
                "status": "generated", "workflow": "anomaly_review",
            })


class LocalHttpTest(IsolatedPipelineTest):
    def setUp(self):
        super().setUp()
        self.seed_attempts()
        handler = type("TestHandler", (Handler,), {"app": self.app, "log_message": lambda *args: None})
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def request(self, method, path, payload=None, raw=None):
        import http.client
        # A real HTTP request reaches Handler, JSON parsing and Database.
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        data = raw if raw is not None else (json.dumps(payload).encode() if payload is not None else None)
        try:
            conn.request(method, path, body=data, headers={"Content-Type": "application/json"})
            response = conn.getresponse()
            content = response.read()
            decoded = json.loads(content) if response.getheader("Content-Type", "").startswith("application/json") else content
            return response.status, decoded
        finally:
            conn.close()
