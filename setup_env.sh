#!/usr/bin/env bash
set -euo pipefail

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"

supports_project() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

resolve_creator() {
  local candidate resolved
  for candidate in "${PIPELINE_PYTHON:-}" python3 python; do
    [[ -n "$candidate" ]] || continue
    if [[ "$candidate" == */* ]]; then
      resolved="$candidate"
    else
      resolved="$(command -v "$candidate" 2>/dev/null || true)"
    fi
    if [[ -x "$resolved" ]] && supports_project "$resolved"; then
      printf '%s\n' "$resolved"
      return 0
    fi
  done
  return 1
}

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  CREATOR="$(resolve_creator || true)"
  if [[ -z "$CREATOR" ]]; then
    echo "错误：创建虚拟环境需要 Python 3.10 或更高版本。" >&2
    echo "可先通过 Homebrew 安装：brew install python@3.12" >&2
    exit 1
  fi
  "$CREATOR" -m venv "$VENV_DIR"
fi

if ! supports_project "$VENV_DIR/bin/python"; then
  echo "错误：现有 .venv 的 Python 版本低于 3.10，请移走该目录后重新执行。" >&2
  exit 1
fi

"$VENV_DIR/bin/python" -m pip install --disable-pip-version-check -r "$PROJECT_DIR/requirements.txt"
printf '%s\n' "$VENV_DIR/bin/python" > "$PROJECT_DIR/python_path.local.txt"

PYTHON_VERSION="$("$VENV_DIR/bin/python" -c 'import platform; print(platform.python_version())')"
PILLOW_VERSION="$("$VENV_DIR/bin/python" -c 'import PIL; print(PIL.__version__)')"
echo "环境已就绪：${VENV_DIR}"
echo "Python ${PYTHON_VERSION}，Pillow ${PILLOW_VERSION}"
echo "下一步：填写 config.json 的 dataset.root，然后执行 ./start_review_tool.sh --check"
