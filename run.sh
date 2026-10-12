#!/usr/bin/env bash
# 一键启动 智慧工地安全巡检平台（FastAPI 后端 + Vue3 前端，前后端分离）
#
# 架构：
#   后端  interfaces/api.py      FastAPI，端口 8000，接口 /api/*
#   前端  frontend/              Vue3 + Vite，端口 5173（需 Node 18+）
#
# 本脚本负责启动后端；前端请另开终端：
#   cd frontend && npm install && npm run dev
# 然后浏览器访问 http://localhost:5173
#
# 说明：本沙箱环境中 torchvision 0.23.0 是 CUDA 构建版，而 torch 是 CPU 版，
# 缺少 CUDA 运行库且无法联网重装，导致 torchvision 无法 import。
# 为此项目自带一个最小 torchvision 桩（_tv_stub/，仅提供 ultralytics 后处理所需的
# 纯 torch 实现 ops.nms），让 YOLO 推理走自带 NMS 跑通。
# 下方把 _tv_stub 加进 PYTHONPATH 即可，无需改动任何已安装包。
#
# 待环境可联网时，正确做法是无视本桩，直接执行：
#   pip install torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cpu
# 并删除 _tv_stub 目录即可恢复正常。

set -e

# 进入脚本所在目录（保证相对路径正确）
cd "$(dirname "$0")"

# 桩模块目录（仅当前沙箱 workaround 需要）
export PYTHONPATH="$(pwd)/_tv_stub:${PYTHONPATH}"

PORT="${API_PORT:-8000}"

echo ">>> 启动 FastAPI 后端 (端口 $PORT, 接口文档 http://localhost:$PORT/docs)"

# 后台启动时重定向日志
if [ "${1:-}" = "-d" ] || [ "${DAEMON:-}" = "1" ]; then
  nohup python3 -m uvicorn interfaces.api:app --host 0.0.0.0 --port "$PORT" > api.log 2>&1 &
  echo ">>> 已在后台启动, PID=$!, 日志: api.log"
  echo ">>> 前端启动: cd frontend && npm install && npm run dev"
else
  exec python3 -m uvicorn interfaces.api:app --host 0.0.0.0 --port "$PORT"
fi
