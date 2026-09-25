"""运行 zyc 的 AI 测试：加载根目录业务代码。"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from TEST._shared.runner import main

if __name__ == "__main__":
    raise SystemExit(main("test_ai", fixed_role="zyc", candidate=False))
