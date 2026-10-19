#!/bin/bash
# Double-click this file in Finder to start the MATSim web UI.
# It reports Docker's state, installs Python deps if needed, starts the server,
# and opens your browser automatically.
APP_PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_PROJECT_DIR" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
  echo "没有找到 Python 3。请先安装 Python 3.10 或更高版本。"
  read -p "按回车键关闭这个窗口..."
  exit 1
fi

if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' \
    >/dev/null 2>&1; then
  echo "Python 版本过旧。请安装 Python 3.10 或更高版本。"
  read -p "按回车键关闭这个窗口..."
  exit 1
fi

# Always use a project-local environment. This avoids relying on packages that
# happened to be installed globally on the original developer's computer.
APP_VENV_DIR="$APP_PROJECT_DIR/.venv"
APP_PYTHON="$APP_VENV_DIR/bin/python"
if [ ! -x "$APP_PYTHON" ]; then
  echo "首次启动，正在创建项目自己的 Python 环境..."
  if ! python3 -m venv "$APP_VENV_DIR"; then
    echo "无法创建 .venv，请检查 Python 安装。"
    read -p "按回车键关闭这个窗口..."
    exit 1
  fi
fi

echo "正在检查 Docker..."
if ! docker info >/dev/null 2>&1; then
  echo "Docker Desktop 尚未启动。网站仍会打开，你可以查看已有结果；"
  echo "需要生成新仿真时，再打开 Docker Desktop 并在网页点‘重新检查’。"
else
  echo "Docker 正常运行。"
fi

echo "正在检查所需的 Python 包..."
if ! "$APP_PYTHON" -c "import fastapi, uvicorn, rasterio" >/dev/null 2>&1; then
  echo "首次运行，正在安装（只需要一次）..."
  if ! "$APP_PYTHON" -m pip install -r requirements.txt; then
    echo "依赖安装失败，请检查网络后重试。"
    read -p "按回车键关闭这个窗口..."
    exit 1
  fi
fi

echo ""
echo "正在启动服务，确认服务就绪后会自动打开浏览器..."
# The launcher detaches the server and points all process output at real files.
# Closing this Terminal window must not break a later Docker job's stdout pipe.
if ! "$APP_PYTHON" -m wrapper.server; then
  echo "请查看 output/service_logs/web.log。已有服务不会被自动终止。"
  read -p "按回车键关闭这个窗口..."
  exit 1
fi
