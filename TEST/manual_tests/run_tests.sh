#!/usr/bin/env bash
set -euo pipefail

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$TEST_DIR/../.." && pwd)"
source "$PROJECT_DIR/find_python.sh"

TEST_PATTERN="${1:-test_*.py}"
cd "$PROJECT_DIR"
exec "$PYTHON_EXE" -B "$TEST_DIR/runner.py" --pattern "$TEST_PATTERN"

