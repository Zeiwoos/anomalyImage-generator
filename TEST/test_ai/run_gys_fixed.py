"""运行 gys 的 AI 测试：加载 AI 第一阶段修复副本。"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from TEST._shared.runner import main

if __name__ == "__main__":
    raise SystemExit(main("test_ai", fixed_role="gys", candidate=True))
