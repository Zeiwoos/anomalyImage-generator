"""运行 zyc 的 10 项真实 API 测试，加载完整修复版；直接运行可能产生费用。"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from TEST._shared.runner import main

if __name__ == '__main__':
    raise SystemExit(main('test_ai', fixed_role='zyc', candidate=True, live_entry=True))
