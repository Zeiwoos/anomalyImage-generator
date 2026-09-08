from __future__ import annotations

import base64
import tempfile
import unittest
import urllib.request
from pathlib import Path

from PIL import Image

from anomaly_factory.speed_test_server import APIBenchmark, _decode_image, _default_source


class SpeedTestTest(unittest.TestCase):
    def test_default_and_uploaded_images_are_safe_png(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            default = _default_source(root / "default.png")
            self.assertTrue(default.is_file())
            with Image.open(default) as opened:
                self.assertEqual(opened.size, (1024, 1024))
                self.assertEqual(opened.mode, "L")
            payload = base64.b64encode(default.read_bytes()).decode("ascii")
            uploaded = _decode_image("data:image/png;base64," + payload, root / "uploaded.png")
            with Image.open(uploaded) as opened:
                self.assertEqual(opened.size, (1024, 1024))

    def test_timed_request_reports_transport_metrics(self) -> None:
        class Headers:
            def items(self): return [("x-request-id", "req_test")]

        class Response:
            status = 200
            headers = Headers()
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return b'{"ok":true}'

        class Opener:
            def open(self, request, timeout=0): return Response()

        benchmark = APIBenchmark.__new__(APIBenchmark)
        benchmark.opener = Opener()
        raw, metrics = benchmark._timed(urllib.request.Request("http://example.test"), 3)
        self.assertEqual(raw, b'{"ok":true}')
        self.assertEqual(metrics["http_status"], 200)
        self.assertEqual(metrics["request_id"], "req_test")
        self.assertEqual(metrics["response_bytes"], len(raw))


if __name__ == "__main__":
    unittest.main()
