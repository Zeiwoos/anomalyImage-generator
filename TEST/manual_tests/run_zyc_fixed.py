"""运行修复副本的 zyc 用例：当前第一阶段仍会暴露 D03、D03b。"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from TEST._shared.runner import main

if __name__ == '__main__':
    raise SystemExit(main('manual_tests', fixed_role='zyc', candidate=True))
