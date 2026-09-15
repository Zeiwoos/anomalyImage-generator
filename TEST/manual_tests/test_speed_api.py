import threading
from unittest.mock import Mock

from PIL import Image

from anomaly_factory.speed_test_server import Handler as SpeedHandler, SpeedTestApplication
from TEST._shared.fixtures import LocalHttpTest


class SpeedApiCases(LocalHttpTest):
    def setUp(self):
        super().setUp()
        # 使用真实的测速 HTTP 处理器和应用，仅替代可能产生费用的网络基准调用。
        app = SpeedTestApplication.__new__(SpeedTestApplication)
        app.benchmark = Mock(base_url="https://example.invalid/", intelligence={}, core={})
        app.output_dir = self.root / "speed"
        app.output_dir.mkdir()
        app.default_source = app.output_dir / "default_source.png"
        Image.new("L", (32, 32), 120).save(app.default_source)
        app.history, app.lock = [], threading.Lock()
        self.speed = app
        self.server.RequestHandlerClass = type("LocalSpeedHandler", (SpeedHandler,), {"app": app})

    def test_B16_speed_config_history_and_result(self):
        """B16：测速配置、历史和图像接口应返回公开配置及正确的文件字节。"""
        self.assertEqual(self.request("GET", "/api/config")[0], 200)
        status, history = self.request("GET", "/api/history")
        self.assertEqual(status, 200)
        self.assertEqual(history["history"], [])
        status, image = self.request("GET", "/api/result/default_source.png")
        self.assertEqual(status, 200)
        self.assertEqual(image, self.speed.default_source.read_bytes())

    def test_B17_speed_invalid_kind_and_unconfirmed_cost(self):
        """B17：无效测速类型和未确认费用的图像调用应在付费执行前失败。"""
        self.assertEqual(self.request("POST", "/api/run", {"kind": "bad"})[0], 400)
        self.assertEqual(self.request("POST", "/api/run", {"kind": "image_edit"})[0], 400)
        self.speed.benchmark.image_edit.assert_not_called()

    def test_B18_speed_dispatch_history_and_busy(self):
        """B18：文本测速调用应记录结果，并发请求应返回 409。"""
        self.speed.benchmark.text.return_value = {"http_status": 200, "total_seconds": 0.01}
        status, result = self.request("POST", "/api/run", {"kind": "text", "prompt": "fixture"})
        self.assertEqual(status, 200)
        self.assertTrue(result["success"])
        self.speed.benchmark.text.assert_called_once_with("fixture")
        self.assertEqual(len(self.speed.history), 1)
        with self.speed.lock:
            self.assertEqual(self.request("POST", "/api/run", {"kind": "text"})[0], 409)
