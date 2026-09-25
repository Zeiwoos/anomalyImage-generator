"""真实 API 测试：加载根目录业务代码和 config.json；直接运行会发送可能计费的请求。"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from TEST._shared.runner import main

if __name__ == '__main__':
    raise SystemExit(main('test_ai', candidate=False, live_entry=True))
