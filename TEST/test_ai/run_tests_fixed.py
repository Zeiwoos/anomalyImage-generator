"""AI 第一阶段离线修复验证：D06 已修复，D04／D05 留到 zyc 第二阶段。"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from TEST._shared.runner import main

if __name__ == '__main__':
    raise SystemExit(main('test_ai', candidate=True))
