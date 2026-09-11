from __future__ import annotations

import argparse
import io
import os
import sys
import unittest
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class Tee(io.TextIOBase):
    def __init__(self, *streams: io.TextIOBase) -> None:
        self.streams = streams

    def write(self, text: str) -> int:
        for stream in self.streams:
            stream.write(text)
            stream.flush()
        return len(text)

    def flush(self) -> None:
        for stream in self.streams:
            stream.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description="anomalyImage-generator 手工接口测试运行器")
    parser.add_argument("--pattern", default="test_*.py", help="unittest发现模式")
    parser.add_argument("--base-url", default="", help="临时覆盖审核后端地址")
    parser.add_argument("--verbosity", type=int, default=2, choices=(1, 2))
    args = parser.parse_args()

    if args.base_url:
        os.environ["ANOMALY_TEST_BASE_URL"] = args.base_url
    reports = ROOT / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    report_path = reports / f"manual_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    suite = unittest.defaultTestLoader.discover(str(ROOT), pattern=args.pattern)
    with report_path.open("w", encoding="utf-8") as report:
        stream = Tee(sys.stderr, report)
        stream.write(f"base_url={os.environ.get('ANOMALY_TEST_BASE_URL', 'config/default')}\n")
        stream.write(f"pattern={args.pattern}\n\n")
        result = unittest.TextTestRunner(stream=stream, verbosity=args.verbosity).run(suite)
    print(f"测试报告：{report_path}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())

