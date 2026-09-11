#!/usr/bin/env bash

# 本文件既可由其他脚本 source，也可直接运行以输出选中的 Python 路径。
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_EXE=""

is_supported_python() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

try_python() {
  local candidate="${1:-}"
  [[ -n "$candidate" ]] || return 1
  if [[ "$candidate" != */* ]]; then
    candidate="$(command -v "$candidate" 2>/dev/null || true)"
  fi
  if [[ -x "$candidate" ]] && is_supported_python "$candidate"; then
    PYTHON_EXE="$candidate"
    return 0
  fi
  return 1
}

if [[ -n "${PIPELINE_PYTHON:-}" ]]; then
  try_python "$PIPELINE_PYTHON" || true
fi

if [[ -z "$PYTHON_EXE" && -f "$PROJECT_DIR/python_path.local.txt" ]]; then
  IFS= read -r local_python < "$PROJECT_DIR/python_path.local.txt" || true
  local_python="${local_python%$'\r'}"
  try_python "$local_python" || true
fi

if [[ -z "$PYTHON_EXE" && -n "${VIRTUAL_ENV:-}" ]]; then
  try_python "$VIRTUAL_ENV/bin/python" || true
fi

if [[ -z "$PYTHON_EXE" && -n "${CONDA_PREFIX:-}" ]]; then
  try_python "$CONDA_PREFIX/bin/python" || true
fi

if [[ -z "$PYTHON_EXE" ]]; then
  try_python "$PROJECT_DIR/.venv/bin/python" || true
fi

if [[ -z "$PYTHON_EXE" ]]; then
  try_python python3 || try_python python || true
fi

if [[ -z "$PYTHON_EXE" ]]; then
  echo "错误：未找到 Python 3.10 或更高版本。" >&2
  if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
    return 1
  fi
  exit 1
fi

export PYTHON_EXE
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  printf '%s\n' "$PYTHON_EXE"
fi

