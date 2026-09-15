#!/usr/bin/env bash
set -euo pipefail

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$PROJECT_DIR/find_python.sh"
cd "$PROJECT_DIR"
exec "$PYTHON_EXE" -B -m anomaly_factory.cli --config "$PROJECT_DIR/config.json" "$@"

