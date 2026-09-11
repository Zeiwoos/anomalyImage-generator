#!/usr/bin/env bash
set -euo pipefail

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$PROJECT_DIR/config.json"

if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "错误：未找到配置文件 $CONFIG_FILE" >&2
  exit 1
fi

source "$PROJECT_DIR/find_python.sh"
cd "$PROJECT_DIR"

if [[ "${1:-}" == "--check" ]]; then
  "$PYTHON_EXE" -B -c "import sys, PIL; print('Python ' + sys.version.split()[0]); print('Pillow ' + PIL.__version__)"
  exec "$PYTHON_EXE" -B -m anomaly_factory.cli --config "$CONFIG_FILE" doctor
fi

exec "$PYTHON_EXE" -B -m anomaly_factory.cli --config "$CONFIG_FILE" review "$@"

