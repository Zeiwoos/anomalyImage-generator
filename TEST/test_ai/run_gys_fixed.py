from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from TEST._shared.runner import main

if __name__ == "__main__":
    raise SystemExit(main("test_ai", fixed_role="gys", candidate=True))




# 测试AI：离线测试修复版——郭叶盛负责部分