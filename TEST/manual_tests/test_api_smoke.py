from __future__ import annotations

from base import ManualApiTestCase


class ReviewApiSmokeTest(ManualApiTestCase):
    def test_health_contract(self) -> None:
        payload = self.client.get_json("/api/health")
        self.assertTrue(payload.get("ok"), payload)
        self.assert_has_keys(payload, "counts", "worker")
        self.assertIsInstance(payload["counts"], dict)
        self.assertIsInstance(payload["worker"], dict)

    def test_items_contract(self) -> None:
        payload = self.client.get_json("/api/items")
        self.assert_has_keys(payload, "items", "counts", "worker")
        self.assertIsInstance(payload["items"], list)
        self.assertIsInstance(payload["counts"], dict)
        self.assertIsInstance(payload["worker"], dict)


if __name__ == "__main__":
    import unittest

    unittest.main(verbosity=2)

