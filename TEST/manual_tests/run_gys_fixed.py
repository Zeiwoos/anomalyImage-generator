"""运行修复副本的 gys 用例：加载 fix_candidates/anomaly_factory。"""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
PROJECT = next(p for p in HERE.parents if (p / 'TEST' / '_shared' / 'runner.py').is_file())
sys.path.insert(0, str(PROJECT))
from TEST._shared.runner import main

if __name__ == '__main__':
    raise SystemExit(main('manual_tests', fixed_role='gys', candidate=True))
