from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from TEST._shared.runner import main

if __name__ == '__main__':
    raise SystemExit(main('test_ai', fixed_role='zyc', candidate=False, live_entry=True))



# deepseek在线测试——朱懿淳负责部分