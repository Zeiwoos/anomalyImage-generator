"""AI 完整离线修复验证：包含 gys 的 D06 和 zyc 的 D04、D05。"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from TEST._shared.runner import main

if __name__ == '__main__':
    raise SystemExit(main('test_ai', candidate=True))
